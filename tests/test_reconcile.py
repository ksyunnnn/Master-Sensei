"""ポジション照合 reconcile_positions のテスト (ADR-030 Phase4)。

判断層 trades が申告する保有ポジション vs 執行事実層 account_transactions(Parquet)
の純ポジションを突合し、乖離(break)を検出する。これが「DBがよくずれる」の機械検出。
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from src.account_ledger import write_transactions_parquet
from src.db import SenseiDB
from src.saxo_client import TradeReport
from src.account_ledger import trade_reports_to_rows


@pytest.fixture
def db(db_conn):
    return SenseiDB(db_conn)


def _ledger_row(instrument, side, qty, order_id, trade_id):
    return {
        "trade_date": date(2026, 6, 1), "settlement_date": date(2026, 6, 2),
        "type": side, "instrument": instrument, "quantity": qty,
        "price_per_unit": 100.0, "amount": -100.0 * qty if side == "buy" else 100.0 * qty,
        "currency": "USD", "fx_rate": 150.0, "amount_jpy": 1.0,
        "realized_pnl": None, "broker_ref": trade_id, "order_id": order_id,
        "account_id": "77800/T126816", "source": "test", "updated_at": datetime(2026, 6, 3),
    }


def test_no_break_when_ledger_matches_trades(db, tmp_path):
    """trades が closed、台帳も net 0 → 乖離なし。"""
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _ledger_row("SOXL", "buy", 3.0, "OA", "TA"),
        _ledger_row("SOXL", "sell", 3.0, "OB", "TB"),
    ], p)
    tid = db.add_trade(instrument="SOXL", direction="long",
                       entry_date=date(2026, 6, 1), entry_price=218.0, quantity=3,
                       broker_ref="OA")
    db.close_trade(tid, exit_date=date(2026, 6, 2), exit_price=243.0)
    breaks = db.reconcile_positions(str(p))
    assert breaks == []


def test_break_when_trades_claims_open_but_ledger_flat(db, tmp_path):
    """trades は filled かつ未手仕舞い(保有3株申告)、台帳は net 0 → break。

    これが今回の trade 12 ドリフト (クローズ済なのに建玉中) の検出。
    """
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _ledger_row("SOXL", "buy", 3.0, "OA", "TA"),
        _ledger_row("SOXL", "sell", 3.0, "OB", "TB"),
    ], p)
    db.add_trade(instrument="SOXL", direction="long",
                 entry_date=date(2026, 6, 1), entry_price=218.0, quantity=3,
                 status="filled", broker_ref="OA")  # exit_date なし = 建玉中申告
    breaks = db.reconcile_positions(str(p))
    assert len(breaks) == 1
    b = breaks[0]
    assert b["instrument"] == "SOXL"
    assert b["trades_open_qty"] == 3.0
    assert b["ledger_net_qty"] == 0.0


def test_break_when_ledger_position_unrecorded(db, tmp_path):
    """台帳に net 2株あるが trades に申告なし → 未記録エントリーの break。"""
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _ledger_row("TQQQ", "buy", 2.0, "OC", "TC"),
    ], p)
    breaks = db.reconcile_positions(str(p))
    assert len(breaks) == 1
    assert breaks[0]["instrument"] == "TQQQ"
    assert breaks[0]["ledger_net_qty"] == 2.0
    assert breaks[0]["trades_open_qty"] == 0.0


def test_placed_trade_not_counted_as_open(db, tmp_path):
    """placed(未約定)は保有ポジションでない。台帳が空でも break にしない。"""
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([], p)
    db.add_trade(instrument="SOXL", direction="long",
                 entry_date=date(2026, 6, 2), entry_price=228.0, quantity=5,
                 status="placed", broker_ref="5409497457")
    breaks = db.reconcile_positions(str(p))
    assert breaks == []
