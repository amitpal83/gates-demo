"""Reads customer policy records from the PostgreSQL container; read-only, parameterised queries only."""
from __future__ import annotations

import datetime
import decimal

import psycopg2
import psycopg2.extras

from ontology_graph import config


def _connect():
    return psycopg2.connect(
        host=config.POLICY_DB_HOST,
        port=config.POLICY_DB_PORT,
        dbname=config.POLICY_DB_NAME,
        user=config.POLICY_DB_USER,
        password=config.POLICY_DB_PASSWORD,
        connect_timeout=5,
    )


def _clean(row: dict) -> dict:
    out = {}
    for key, value in row.items():
        if isinstance(value, (datetime.date, datetime.datetime)):
            out[key] = value.isoformat()
        elif isinstance(value, decimal.Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out


def list_policies() -> list[dict]:
    with _connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT p.policy_number, c.full_name, p.mode_code FROM customer_policy p "
            "JOIN customers c USING (customer_id) ORDER BY p.policy_number"
        )
        return [dict(row) for row in cur.fetchall()]


def get_policy(policy_number: str) -> dict | None:
    """The policy joined to its customer; mode_code is returned raw, with no meaning attached."""
    with _connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT p.*, c.full_name, c.date_of_birth, c.city FROM customer_policy p "
            "JOIN customers c USING (customer_id) WHERE p.policy_number = %s",
            (policy_number,),
        )
        row = cur.fetchone()
        return _clean(dict(row)) if row else None


def column_notes() -> dict[str, str]:
    """The database's own column comments (its data dictionary), keyed by column name."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT a.attname, d.description FROM pg_description d "
            "JOIN pg_attribute a ON a.attrelid = d.objoid AND a.attnum = d.objsubid "
            "WHERE d.objoid = 'customer_policy'::regclass AND d.objsubid > 0 ORDER BY a.attnum"
        )
        return {name: text for name, text in cur.fetchall()}
