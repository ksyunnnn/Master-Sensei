"""account_ledger の変換ロジックのテスト (ADR-030 Phase3)。

執行事実層 account_transactions(Parquet) は Saxo reports/trades の全 mirror。
TradeReport → 台帳行へのマッピングが正しいことを検証する。
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from src.account_ledger import ACCOUNT_TX_COLUMNS, trade_reports_to_rows
from src.saxo_client import TradeReport


def _buy():
    return TradeReport(
        trade_id="6732724591", order_id="5409009626", account_id="77800/T126816",
        side="buy", quantity=3.0, amount_signed=3.0, price=218.0,
        trade_date=date(2026, 6, 1), value_date=date(2026, 6, 2),
        execution_time_utc="2026-06-01T13:51:47.737000Z",
        booked_amount_usd=-655.77, booked_amount_account_currency=-104712.0,
        account_currency="JPY", instrument_symbol="SOXL:arcx", uic=46780,
        asset_type="Etf", spread_cost_usd=0.0,
    )


def _sell():
    return TradeReport(
        trade_id="6734709190", order_id="5409035181", account_id="77800/T126816",
        side="sell", quantity=3.0, amount_signed=-3.0, price=243.18,
        trade_date=date(2026, 6, 2), value_date=date(2026, 6, 3),
        execution_time_utc="2026-06-02T13:30:00.233000Z",
        booked_amount_usd=727.05, booked_amount_account_currency=116283.0,
        account_currency="JPY", instrument_symbol="SOXL:arcx", uic=46780,
        asset_type="Etf", spread_cost_usd=0.0,
    )


UPDATED = datetime(2026, 6, 3, 12, 0, 0)


def test_maps_all_columns():
    rows = trade_reports_to_rows([_buy()], source="saxo_reports_trades", updated_at=UPDATED)
    assert len(rows) == 1
    assert set(rows[0].keys()) == set(ACCOUNT_TX_COLUMNS)


def test_buy_row_values():
    row = trade_reports_to_rows([_buy()], source="s", updated_at=UPDATED)[0]
    assert row["trade_date"] == date(2026, 6, 1)
    assert row["settlement_date"] == date(2026, 6, 2)
    assert row["type"] == "buy"
    assert row["instrument"] == "SOXL"          # symbol 部のみ (":arcx" を除去)
    assert row["quantity"] == 3.0
    assert row["price_per_unit"] == 218.0
    assert row["amount"] == -655.77             # USD, 買=負
    assert row["currency"] == "USD"
    assert row["amount_jpy"] == -104712.0
    assert row["broker_ref"] == "6732724591"    # TradeId = fill 主キー
    assert row["order_id"] == "5409009626"      # OrderId = trades 結合キー
    assert row["account_id"] == "77800/T126816"
    assert row["source"] == "s"
    assert row["updated_at"] == UPDATED


def test_fx_rate_is_positive_jpy_per_usd():
    """fx_rate = |JPY/USD|。符号に依存せず正。"""
    buy = trade_reports_to_rows([_buy()], source="s", updated_at=UPDATED)[0]
    sell = trade_reports_to_rows([_sell()], source="s", updated_at=UPDATED)[0]
    assert buy["fx_rate"] == pytest.approx(104712.0 / 655.77, rel=1e-6)
    assert buy["fx_rate"] > 0
    assert sell["fx_rate"] > 0


def test_sell_type_and_signs():
    row = trade_reports_to_rows([_sell()], source="s", updated_at=UPDATED)[0]
    assert row["type"] == "sell"
    assert row["amount"] > 0                     # 売=正 (cash in)
    assert row["quantity"] == 3.0                # 数量は常に正


def test_realized_pnl_is_none():
    """reports/trades は fill 単位の実現損益を持たない → None。"""
    row = trade_reports_to_rows([_buy()], source="s", updated_at=UPDATED)[0]
    assert row["realized_pnl"] is None


def test_zero_usd_amount_fx_rate_none():
    """BookedAmountUSD=0 で fx_rate がゼロ除算しない。"""
    r = _buy()
    r.booked_amount_usd = 0.0
    row = trade_reports_to_rows([r], source="s", updated_at=UPDATED)[0]
    assert row["fx_rate"] is None


def test_empty_input():
    assert trade_reports_to_rows([], source="s", updated_at=UPDATED) == []
