"""
PostgreSQL data access layer.

The public API intentionally matches the original database module so existing
routes and CSV import code can evolve without changing every caller at once.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from datetime import date, datetime
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from backend.config import DATABASE_URL


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)


@contextmanager
def get_connection():
    with engine.begin() as conn:
        yield conn


def quote_identifier(identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise ValueError("Invalid SQL identifier")
    return '"' + identifier.replace('"', '""') + '"'


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _run_select(conn: Connection, sql: str, params: dict | None = None) -> list[dict]:
    result = conn.execute(text(sql), params or {})
    return [dict(row._mapping) for row in result]


def get_table_names(include_system: bool = False) -> list[str]:
    sql = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """
    with get_connection() as conn:
        tables = [row["table_name"] for row in _run_select(conn, sql)]
    if include_system:
        return tables
    return [t for t in tables if not t.startswith("knowledge_")]


def get_ddl() -> str:
    """Return PostgreSQL-style CREATE TABLE metadata for LLM context."""
    sql = """
        SELECT
            c.table_name,
            c.column_name,
            c.data_type,
            c.character_maximum_length,
            c.numeric_precision,
            c.numeric_scale,
            c.is_nullable,
            c.column_default,
            obj_description(format('%I.%I', c.table_schema, c.table_name)::regclass) AS table_comment,
            col_description(format('%I.%I', c.table_schema, c.table_name)::regclass::oid, c.ordinal_position) AS column_comment
        FROM information_schema.columns c
        WHERE c.table_schema = 'public'
        ORDER BY c.table_name, c.ordinal_position
    """
    with get_connection() as conn:
        rows = _run_select(conn, sql)

    grouped: dict[str, list[dict]] = {}
    comments: dict[str, str | None] = {}
    for row in rows:
        table_name = row["table_name"]
        if table_name.startswith("knowledge_"):
            continue
        grouped.setdefault(table_name, []).append(row)
        comments[table_name] = row.get("table_comment")

    ddl_parts: list[str] = []
    for table_name, columns in grouped.items():
        ddl_parts.append(f'CREATE TABLE "{table_name}" (')
        col_lines = []
        for col in columns:
            data_type = _format_pg_type(col)
            nullable = "NOT NULL" if col["is_nullable"] == "NO" else "NULL"
            default = f" DEFAULT {col['column_default']}" if col.get("column_default") else ""
            comment = f" -- {col['column_comment']}" if col.get("column_comment") else ""
            col_lines.append(
                f'  "{col["column_name"]}" {data_type} {nullable}{default}{comment}'
            )
        ddl_parts.append(",\n".join(col_lines))
        table_comment = f" -- {comments.get(table_name)}" if comments.get(table_name) else ""
        ddl_parts.append(f");{table_comment}\n")
    return "\n".join(ddl_parts).strip()


def _format_pg_type(col: dict) -> str:
    data_type = col["data_type"]
    if data_type == "character varying" and col.get("character_maximum_length"):
        return f'VARCHAR({col["character_maximum_length"]})'
    if data_type == "numeric" and col.get("numeric_precision"):
        scale = col.get("numeric_scale") or 0
        return f'NUMERIC({col["numeric_precision"]},{scale})'
    if data_type == "timestamp with time zone":
        return "TIMESTAMPTZ"
    if data_type == "timestamp without time zone":
        return "TIMESTAMP"
    return data_type.upper()


def execute_sql(sql: str) -> dict:
    with get_connection() as conn:
        rows = _run_select(conn, sql)
    if not rows:
        return {"columns": [], "data": [], "row_count": 0}
    columns = list(rows[0].keys())
    data = [[_json_value(row[col]) for col in columns] for row in rows]
    return {"columns": columns, "data": data, "row_count": len(data)}


def execute_ddl(sql: str) -> None:
    with get_connection() as conn:
        conn.execute(text(sql))


def execute_insert(sql: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    with get_connection() as conn:
        result = conn.execute(text(sql), rows)
        return result.rowcount or len(rows)


def table_exists(table_name: str) -> bool:
    sql = """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = :table_name
    """
    with get_connection() as conn:
        return conn.execute(text(sql), {"table_name": table_name}).first() is not None


def drop_table(table_name: str) -> None:
    if not table_name.startswith("csv_"):
        raise ValueError(
            f"安全限制：不允许删除非导入表 '{table_name}'。只有 csv_ 前缀的导入表可以被删除。"
        )
    execute_ddl(f"DROP TABLE IF EXISTS {quote_identifier(table_name)}")
