"""account_ledger の変換ロジックのテスト (ADR-030 Phase3)。

執行事実層 account_transactions(Parquet) は Saxo reports/trades の全 mirror。
TradeReport → 台帳行へのマッピングが正しいことを検証する。
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from src.account_ledger import (
    ACCOUNT_TX_COLUMNS,
    cash_bookings_to_rows,
    trade_reports_to_rows,
)
from src.saxo_client import CashBooking, TradeReport


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


# --- 現金移動 (deposit/withdrawal) の写像 (ADR-030 Phase 5) ---


def _transfer_in():
    """2026-06-03 live で観測した口座間振替 (CASHINTRTP, +50,000 JPY)。"""
    return CashBooking(
        booking_id="53283970258", account_id="77800/T126816",
        date=date(2026, 3, 11), value_date=date(2026, 3, 11),
        amount_usd=314.53, amount_account_currency=50000.0, account_currency="JPY",
        symbol="CASHINTRTP", description="Interaccount transfer within different client in S",
    )


def _withdrawal():
    """符号が負の現金移動 (cash out)。外部入出金の符号表現は未観測のため合成。"""
    return CashBooking(
        booking_id="99999999999", account_id="77800/T126816",
        date=date(2026, 4, 1), value_date=date(2026, 4, 2),
        amount_usd=-200.0, amount_account_currency=-31700.0, account_currency="JPY",
        symbol="CASHWD", description="Cash withdrawal",
    )


def test_cash_maps_all_columns():
    rows = cash_bookings_to_rows([_transfer_in()], source="saxo_reports_bookings", updated_at=UPDATED)
    assert len(rows) == 1
    assert set(rows[0].keys()) == set(ACCOUNT_TX_COLUMNS)


def test_cash_in_is_deposit():
    row = cash_bookings_to_rows([_transfer_in()], source="s", updated_at=UPDATED)[0]
    assert row["type"] == "deposit"          # AmountUSD >= 0
    assert row["amount"] == 314.53           # USD, cash in は正
    assert row["amount"] > 0
    assert row["currency"] == "USD"
    assert row["amount_jpy"] == 50000.0
    assert row["trade_date"] == date(2026, 3, 11)
    assert row["settlement_date"] == date(2026, 3, 11)


def test_cash_out_is_withdrawal():
    row = cash_bookings_to_rows([_withdrawal()], source="s", updated_at=UPDATED)[0]
    assert row["type"] == "withdrawal"       # AmountUSD < 0
    assert row["amount"] < 0                  # cash out は負


def test_cash_preserves_symbol_in_instrument():
    """元の性質 (口座間振替 CASHINTRTP 等) を instrument に保持し可逆にする。"""
    row = cash_bookings_to_rows([_transfer_in()], source="s", updated_at=UPDATED)[0]
    assert row["instrument"] == "CASHINTRTP"


def test_cash_has_no_quantity_or_price():
    """現金行は株数・単価を持たない (NULL)。"""
    row = cash_bookings_to_rows([_transfer_in()], source="s", updated_at=UPDATED)[0]
    assert row["quantity"] is None
    assert row["price_per_unit"] is None


def test_cash_broker_ref_is_booking_id_no_order():
    """現金行の主キーは BkAmountId。注文を伴わないので order_id は None。"""
    row = cash_bookings_to_rows([_transfer_in()], source="s", updated_at=UPDATED)[0]
    assert row["broker_ref"] == "53283970258"
    assert row["order_id"] is None


def test_cash_fx_rate_positive():
    row = cash_bookings_to_rows([_transfer_in()], source="s", updated_at=UPDATED)[0]
    assert row["fx_rate"] == pytest.approx(50000.0 / 314.53, rel=1e-6)
    assert row["fx_rate"] > 0


def test_cash_zero_usd_fx_rate_none():
    b = _transfer_in()
    b.amount_usd = 0.0
    row = cash_bookings_to_rows([b], source="s", updated_at=UPDATED)[0]
    assert row["fx_rate"] is None
    assert row["type"] == "deposit"          # 0 は deposit 側 (>= 0)


def test_cash_realized_pnl_none():
    row = cash_bookings_to_rows([_transfer_in()], source="s", updated_at=UPDATED)[0]
    assert row["realized_pnl"] is None


def test_cash_empty_input():
    assert cash_bookings_to_rows([], source="s", updated_at=UPDATED) == []
