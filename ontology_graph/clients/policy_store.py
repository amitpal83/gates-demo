"""Reads policy records from the PostgreSQL container; read-only, parameterised queries only."""
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
        cur.execute("SELECT policy_number, holder_name FROM policies ORDER BY policy_number")
        return [dict(row) for row in cur.fetchall()]


def get_policy(policy_number: str) -> dict | None:
    with _connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM policies WHERE policy_number = %s", (policy_number,))
        row = cur.fetchone()
        if row is None:
            return None
        record = _clean(dict(row))
        cur.execute(
            "SELECT txn_date, txn_type, amount_inr, note FROM policy_transactions WHERE policy_number = %s ORDER BY txn_date",
            (policy_number,),
        )
        record["transactions"] = [_clean(dict(txn)) for txn in cur.fetchall()]
        return record
