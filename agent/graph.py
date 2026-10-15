"""LangGraph text-to-SQL agent over the ZoneShift DuckDB marts.

load_schema -> generate_sql -> guard -> execute -> answer
                   ^             |          |
                   +-- repair <--+----------+   (on guard or execution error, at most 2 repairs)
"""
import re
import threading
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent.guard import GuardError, guard
from agent.llm import chat
from agent.schema import connect, schema_context

MAX_REPAIRS = 2
QUERY_TIMEOUT_S = 60
ANSWER_ROWS = 30

SYSTEM = """You translate questions about NYC taxi data into a single DuckDB SQL SELECT query.
Rules:
- Use only the tables and columns in the schema below; never invent columns.
- One SELECT statement (CTEs allowed). No DDL/DML, no file or table functions.
- Return exactly the columns the question asks for, in a sensible order, with readable aliases.
- Round decimals only when the question asks for rounding.
- Reply with the SQL in one ```sql code block and nothing else.

SCHEMA:
{schema}"""


class State(TypedDict, total=False):
    question: str
    with_answer: bool
    schema: str
    sql: str
    safe_sql: str
    error: str
    attempts: int
    columns: list[str]
    rows: list[tuple]
    answer: str


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip().rstrip(";").strip()


def load_schema(state: State) -> State:
    return {"schema": schema_context(), "attempts": 0, "error": ""}


def generate_sql(state: State) -> State:
    reply = chat([{"role": "system", "content": SYSTEM.format(schema=state["schema"])},
                  {"role": "user", "content": state["question"]}])
    return {"sql": extract_sql(reply), "attempts": state["attempts"] + 1, "error": ""}


def repair_sql(state: State) -> State:
    reply = chat([
        {"role": "system", "content": SYSTEM.format(schema=state["schema"])},
        {"role": "user", "content": state["question"]},
        {"role": "assistant", "content": f"```sql\n{state['sql']}\n```"},
        {"role": "user", "content": f"That query failed:\n{state['error']}\n"
                                    "Return a corrected query in one ```sql code block."},
    ])
    return {"sql": extract_sql(reply), "attempts": state["attempts"] + 1, "error": ""}


def guard_sql(state: State) -> State:
    try:
        return {"safe_sql": guard(state["sql"]), "error": ""}
    except GuardError as e:
        return {"error": f"Guard rejected the query: {e}"}


def execute(state: State) -> State:
    con = connect()
    timer = threading.Timer(QUERY_TIMEOUT_S, con.interrupt)
    timer.start()
    try:
        cur = con.execute(state["safe_sql"])
        cols = [d[0] for d in cur.description]
        return {"columns": cols, "rows": cur.fetchall(), "error": ""}
    except Exception as e:  # noqa: BLE001 - every engine error goes back to the model
        msg = str(e).splitlines()[0][:500]
        if "interrupted" in msg.lower():
            msg = f"Query exceeded {QUERY_TIMEOUT_S}s; use aggregate tables or simpler joins."
        return {"error": f"Execution error: {msg}"}
    finally:
        timer.cancel()
        con.close()


def answer(state: State) -> State:
    preview = "\n".join(str(r) for r in state["rows"][:ANSWER_ROWS])
    reply = chat([{"role": "user", "content": (
        f"Question: {state['question']}\nSQL:\n{state['safe_sql']}\nColumns: {state['columns']}\n"
        f"Rows ({len(state['rows'])} total, first {ANSWER_ROWS} shown):\n{preview}\n\n"
        "Answer the question in 1-3 plain sentences using only these results. Neutral tone.")}],
        max_tokens=1500)
    return {"answer": reply.strip()}


def route_after_check(state: State) -> str:
    if state.get("error"):
        return "repair" if state["attempts"] <= MAX_REPAIRS else END
    return "ok"


def build():
    g = StateGraph(State)
    for name, fn in [("load_schema", load_schema), ("generate_sql", generate_sql), ("repair", repair_sql),
                     ("guard", guard_sql), ("execute", execute), ("answer", answer)]:
        g.add_node(name, fn)
    g.add_edge(START, "load_schema")
    g.add_edge("load_schema", "generate_sql")
    g.add_edge("generate_sql", "guard")
    g.add_edge("repair", "guard")
    g.add_conditional_edges("guard", route_after_check, {"repair": "repair", "ok": "execute", END: END})
    g.add_conditional_edges(
        "execute",
        lambda s: route_after_check(s) if s.get("error") else ("answer" if s.get("with_answer", True) else END),
        {"repair": "repair", "answer": "answer", END: END})
    g.add_edge("answer", END)
    return g.compile()


_graph = None


def run(question: str, with_answer: bool = True) -> State:
    global _graph
    _graph = _graph or build()
    return _graph.invoke({"question": question, "with_answer": with_answer})
