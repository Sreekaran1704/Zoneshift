"""SQL guard: one read-only SELECT over allowlisted marts tables, with an enforced row limit.

The DuckDB connection is also opened read-only with external file access disabled, so the guard
is the first of two layers, not the only one.
"""
import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {"fct_trips", "agg_zone_day", "agg_zone_hour", "dim_zone", "dim_date"}
ALLOWED_SCHEMA = "marts"
MAX_ROWS = 1000
WRITE_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command,
               exp.Copy, exp.Pragma, exp.Set, exp.Merge, exp.TruncateTable, exp.Attach, exp.Detach,
               exp.Use, exp.Transaction, exp.Commit, exp.Rollback, exp.Describe)


class GuardError(ValueError):
    pass


def guard(sql: str, max_rows: int = MAX_ROWS) -> str:
    """Return a safe, schema-qualified, row-limited version of `sql` or raise GuardError."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise GuardError(f"SQL could not be parsed: {str(e).splitlines()[0]}") from e
    if len(statements) != 1:
        raise GuardError(f"Exactly one statement is allowed, got {len(statements)}.")
    stmt = statements[0]
    if not isinstance(stmt, exp.Query):
        raise GuardError(f"Only SELECT queries are allowed, got {type(stmt).__name__}.")
    if any(isinstance(node, WRITE_NODES) for node in stmt.walk()):
        raise GuardError("Only read-only SELECT queries are allowed.")

    ctes = {c.alias_or_name.lower() for c in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):  # table functions: read_parquet(...), etc.
            raise GuardError(f"Table functions are not allowed: {table.this.sql('duckdb')[:60]}")
        name, schema = table.name.lower(), table.db.lower()
        if not schema and name in ctes:
            continue
        if table.catalog or name not in ALLOWED_TABLES or schema not in ("", ALLOWED_SCHEMA):
            allowed = ", ".join(f"{ALLOWED_SCHEMA}.{t}" for t in sorted(ALLOWED_TABLES))
            raise GuardError(f"Table {table.sql('duckdb')} is not allowed. Use only: {allowed}.")
        table.set("db", exp.to_identifier(ALLOWED_SCHEMA))

    limit = stmt.args.get("limit")
    if limit is None:
        stmt = stmt.limit(max_rows)
    else:
        try:
            n = int(limit.expression.name)
        except (AttributeError, ValueError):
            n = max_rows + 1
        if n > max_rows:
            stmt = stmt.limit(max_rows)
    return stmt.sql(dialect="duckdb")
