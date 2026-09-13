"""執行事実層(Parquet)から残存建玉と取得原価を導出する get_ledger_positions のテスト。

Saxo 認証なしで建玉の含み損益を出せるようにするための土台。既存の
`scripts/position_pnl.py` はライブ API に依存するためトークン失効中は動かないが、
台帳 Parquet はローカルにあるので失効中でも建玉を出せる。

検証する不変条件:
  - 原価は `amount`(手数料込みの実約定金額)であって price_per_unit * quantity ではない
  - FIFO で古い lot から消し込む(決済済み lot が残存建玉の建値を汚染しない)
  - 残数量 0 の instrument は建玉として返さない
  - 台帳ファイルが無くても例外にしない
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from src.account_ledger import write_transactions_parquet
from src.db import SenseiDB


@pytest.fixture
def db(db_conn):
    return SenseiDB(db_conn)


def _row(instrument, side, qty, price, amount, *, day, order_id="O1"):
    """台帳1行。amount は買い負(出金)・売り正(入金)で手数料込み。"""
    return {
        "trade_date": date(2026, 8, day), "settlement_date": date(2026, 8, day + 1),
        "type": side, "instrument": instrument, "quantity": qty,
        "price_per_unit": price, "amount": amount,
        "currency": "USD", "fx_rate": 150.0, "amount_jpy": amount * 150.0,
        "realized_pnl": None, "broker_ref": order_id, "order_id": order_id,
        "account_id": "77800/T126816", "source": "test",
        "updated_at": datetime(2026, 9, 1),
    }


def test_single_buy_reports_quantity_and_cost(db, tmp_path):
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _row("SOXL", "buy", 25.0, 119.879, -3004.84, day=20),
    ], p)

    pos = db.get_ledger_positions(str(p))

    assert set(pos) == {"SOXL"}
    assert pos["SOXL"].quantity == pytest.approx(25.0)
    assert pos["SOXL"].cost_usd == pytest.approx(3004.84)


def test_cost_basis_includes_commission_not_price_times_quantity(db, tmp_path):
    """建値は amount 由来。price_per_unit * quantity では手数料が落ちる。

    25 * 119.879 = 2996.98 に対し実際の出金は 3004.84。差の 7.86 が手数料で、
    これを落とすと建値が実際より低く出て損益が過大評価される。
    """
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _row("SOXL", "buy", 25.0, 119.879, -3004.84, day=20),
    ], p)

    pos = db.get_ledger_positions(str(p))

    assert pos["SOXL"].avg_price == pytest.approx(120.1936, abs=1e-4)
    assert pos["SOXL"].avg_price > 119.879


def test_fifo_consumes_oldest_lot_first(db, tmp_path):
    """決済済みの高値 lot は残存建玉の建値に混ざらない。

    8/18 に 134.13 で 24株買い、8/19 に 120.03 で 24株決済、8/20 に 119.879 で 25株買い。
    残るのは 8/20 の lot だけなので建値は 120.194。平均法だと 127 前後に汚染される。
    """
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _row("SOXL", "buy", 12.0, 134.130, -1615.30, day=18, order_id="A"),
        _row("SOXL", "buy", 12.0, 134.130, -1615.30, day=18, order_id="B"),
        _row("SOXL", "sell", 12.0, 120.030, 1437.84, day=19, order_id="C"),
        _row("SOXL", "sell", 12.0, 120.030, 1437.84, day=19, order_id="D"),
        _row("SOXL", "buy", 25.0, 119.879, -3004.84, day=20, order_id="E"),
    ], p)

    pos = db.get_ledger_positions(str(p))

    assert pos["SOXL"].quantity == pytest.approx(25.0)
    assert pos["SOXL"].cost_usd == pytest.approx(3004.84)
    assert pos["SOXL"].avg_price == pytest.approx(120.1936, abs=1e-4)
    assert pos["SOXL"].opened_on == date(2026, 8, 20)


def test_partial_sell_leaves_remainder_of_oldest_lot(db, tmp_path):
    """lot の一部だけ決済したら、残り数量ぶんの原価だけが残る。"""
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _row("SOXL", "buy", 10.0, 100.0, -1000.0, day=18, order_id="A"),
        _row("SOXL", "sell", 4.0, 110.0, 440.0, day=19, order_id="B"),
    ], p)

    pos = db.get_ledger_positions(str(p))

    assert pos["SOXL"].quantity == pytest.approx(6.0)
    assert pos["SOXL"].cost_usd == pytest.approx(600.0)
    assert pos["SOXL"].avg_price == pytest.approx(100.0)


def test_fully_closed_instrument_is_absent(db, tmp_path):
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _row("SOXL", "buy", 3.0, 100.0, -300.0, day=18, order_id="A"),
        _row("SOXL", "sell", 3.0, 110.0, 330.0, day=19, order_id="B"),
    ], p)

    assert db.get_ledger_positions(str(p)) == {}


def test_same_day_round_trip_buys_before_sells(db, tmp_path):
    """同日の買いと売りは買いを先に消し込む(存在しない lot を売らない)。

    trade_date だけで並べると売りが先に来て「在庫なしの売り」になり、
    残数量が負に振れて建玉を誤って報告する。
    """
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _row("SOXL", "sell", 4.0, 110.0, 440.0, day=18, order_id="S"),
        _row("SOXL", "buy", 4.0, 100.0, -400.0, day=18, order_id="B"),
    ], p)

    assert db.get_ledger_positions(str(p)) == {}


def test_non_trade_rows_are_ignored(db, tmp_path):
    """入金(deposit)など buy/sell 以外の行は建玉計算に混ぜない。"""
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _row("CASHINTRTP", "deposit", None, None, 1252.06, day=25),
        _row("SOXL", "buy", 5.0, 100.0, -500.0, day=20),
    ], p)

    pos = db.get_ledger_positions(str(p))

    assert set(pos) == {"SOXL"}


def test_missing_parquet_returns_empty(db, tmp_path):
    """台帳がまだ無い環境(fresh clone)でも例外にしない。"""
    assert db.get_ledger_positions(str(tmp_path / "absent.parquet")) == {}


def test_multiple_instruments_are_separated(db, tmp_path):
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _row("SOXL", "buy", 5.0, 100.0, -500.0, day=20, order_id="A"),
        _row("TQQQ", "buy", 2.0, 70.0, -140.0, day=21, order_id="B"),
    ], p)

    pos = db.get_ledger_positions(str(p))

    assert pos["SOXL"].quantity == pytest.approx(5.0)
    assert pos["TQQQ"].cost_usd == pytest.approx(140.0)
