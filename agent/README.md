# Text-to-SQL agent

Ask questions about the ZoneShift marts in plain English (`make ask`, or
`python -m agent.cli "your question"`). Built with LangGraph and a Groq-hosted model
(`openai/gpt-oss-120b` by default; override with `GROQ_MODEL` in `.env`).

```
load_schema -> generate_sql -> guard -> execute -> answer
                    ^            |         |
                    +-- repair <-+---------+    (guard or execution error; at most 2 repairs)
```

- **Schema context** (`schema.py`): the five allowlisted marts with their dbt model and column
  descriptions (from `dbt/zoneshift/target/manifest.json`) and actual DuckDB column types, plus
  notes on traps such as the `service_type = 'all'` rows.
- **Guard** (`guard.py`): parses with sqlglot; allows one read-only SELECT (CTEs/unions OK) on
  `marts.fct_trips`, `agg_zone_day`, `agg_zone_hour`, `dim_zone`, `dim_date` only; rejects DDL/DML,
  table functions and file paths; schema-qualifies tables; enforces `LIMIT 1000`.
- **Execution** (`graph.py`): DuckDB opened read-only with external file access disabled (second
  layer), 60 s timeout.
- **Answer**: a short neutral summary of the result, always shown with the SQL that produced it.

## Evaluation

`agent/eval/gold_questions.yaml`: 45 questions (15 easy, 18 medium, 12 hard) with gold SQL;
`gold_review.md` shows each with its gold result. `make agent-eval` scores execution accuracy:
result sets must match (row order ignored unless the question asks for an order, column names
ignored, floats within max(0.01, 1e-4 x |gold|)). Runs are cached in
`results/agent_eval_runs.jsonl`, so a rate-limited run resumes; the summary goes to
`results/metrics.json` under `agent_eval`. The scorer refuses to run until the question set is
marked `reviewed: true`.
