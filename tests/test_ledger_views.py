"""SenseiDB.ensure_ledger_views (ADR-035) テスト。

執行事実層 parquet を duckdb ビュー化し、read-only MCP からパス/カラムを知らずに
照会できるようにする。存在ガード(fresh clone で壊れない)も検証する。
"""
from __future__ import annotations

import pandas as pd

from src.db import SenseiDB


def test_ensure_ledger_views_creates_queryable_view(tmp_path, db_conn):
    pq = tmp_path / "transactions.parquet"
    pd.DataFrame({
        "instrument": ["SOXL"], "type": ["buy"], "quantity": [3.0],
        "price_per_unit": [165.4], "order_id": ["5421812530"],
    }).to_parquet(pq)

    db = SenseiDB(db_conn)
    assert db.ensure_ledger_views(str(pq)) is True

    row = db_conn.execute(
        "SELECT instrument, price_per_unit, order_id FROM account_transactions"
    ).fetchone()
    assert row == ("SOXL", 165.4, "5421812530")


def test_ensure_ledger_views_noop_when_parquet_absent(tmp_path, db_conn):
    db = SenseiDB(db_conn)
    # parquet 不在 → False を返し、例外を投げない(fresh clone で RW 接続を壊さない)
    assert db.ensure_ledger_views(str(tmp_path / "nope.parquet")) is False
