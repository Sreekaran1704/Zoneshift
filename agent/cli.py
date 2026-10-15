"""Ask questions about the ZoneShift marts in plain English.

Usage:
    python -m agent.cli "Which 5 zones had the most pickups in 2025?"
    python -m agent.cli            # interactive
"""
import sys

from agent.graph import run
from agent.llm import model_name


def ask(question: str) -> None:
    s = run(question)
    print(f"\nSQL ({model_name()}, {s.get('attempts', 0)} attempt(s)):\n{s.get('safe_sql') or s.get('sql')}\n")
    if s.get("error"):
        print(f"Failed: {s['error']}")
        return
    print(" | ".join(s["columns"]))
    for r in s["rows"][:20]:
        print(" | ".join(str(v) for v in r))
    if len(s["rows"]) > 20:
        print(f"... {len(s['rows'])} rows")
    print(f"\n{s['answer']}")


def main() -> None:
    if len(sys.argv) > 1:
        ask(" ".join(sys.argv[1:]))
        return
    print("ZoneShift SQL agent. Empty line to quit.")
    while q := input("\n> ").strip():
        ask(q)


if __name__ == "__main__":
    main()
