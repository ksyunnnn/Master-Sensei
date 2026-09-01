"""live_reads (ADR-035) ユニットテスト。

MCP サーバの behavior 本体 = 純粋な serializer / 接続モード判定 / リトライ /
payload 関数。MCP ランタイムに依存せずここで固定する（mcp_saxo.py は薄い glue）。
DB/HTTP は fake で差し替える（実 live 検証は Phase 3）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from src import live_reads
from src.live_reads import (
    AuthRequired,
    _retry_on_lock,
    balance_to_dict,
    decide_mode,
    order_to_dict,
    position_to_dict,
    quote_to_dict,
    trade_cost_to_dict,
)
from src.realtime import RealtimeQuote
from src.saxo_client import AccountBalance, LivePosition, OpenOrder, TradeCost

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 7, 8, 12, 0, tzinfo=JST)


# ── serializers: 全 field を正しい名前で写像する（ADR-026 の "推測させない" 核心） ──

def _balance() -> AccountBalance:
    return AccountBalance(
        # 実口座の account_key を書かない (公開リポジトリ)。形式だけ模した固定値を使う
        account_id="77800/T126816", account_key="TESTKEY0000000000000000==",
        currency="JPY", spending_power=79957.0, cash_available_for_trading=79957.0,
        settled_cash_balance=160663.0, total_value=427980.0,
        # 時価 348,022 − 決済コスト 320。含み損益ではない (K-081)
        unrealized_positions_value=347702.0,
        transactions_not_booked=-80706.0, open_positions_count=2, net_positions_count=1,
        non_margin_positions_value=348022.0, calculation_reliability="Ok",
    )


def test_balance_to_dict_maps_every_field():
    d = balance_to_dict(_balance())
    assert set(d) == {
        "account_id", "account_key", "currency", "spending_power",
        "cash_available_for_trading", "settled_cash_balance", "total_value",
        "unrealized_positions_value", "transactions_not_booked", "open_positions_count",
        "net_positions_count", "non_margin_positions_value", "calculation_reliability",
    }
    # sizing に使う値と使わない値の両方が正しい名前で出る
    assert d["spending_power"] == 79957.0
    assert d["settled_cash_balance"] == 160663.0
    assert d["account_id"] == "77800/T126816"


def test_position_to_dict_maps_fields():
    p = LivePosition(account_id="77800/T126816", uic=46780, symbol="SOXL",
                     amount=3.0, open_price=165.4, unrealized_pnl_base=-39.0)
    d = position_to_dict(p)
    assert set(d) == {"account_id", "uic", "symbol", "amount", "open_price",
                      "unrealized_pnl_base"}
    assert d["symbol"] == "SOXL" and d["amount"] == 3.0 and d["open_price"] == 165.4


def test_order_to_dict_maps_fields():
    o = OpenOrder(order_id="5421812528", account_id="77800/T126816", uic=46780,
                  symbol="SOXL", amount=10.0, buy_sell="Sell",
                  order_type="StopIfTraded", price=100.0, status="Working")
    d = order_to_dict(o)
    assert set(d) == {"order_id", "account_id", "uic", "symbol", "amount",
                      "buy_sell", "order_type", "price", "status"}
    assert d["order_id"] == "5421812528" and d["price"] == 100.0


def test_order_to_dict_price_none_for_market():
    o = OpenOrder(order_id="1", account_id="a", uic=46780, symbol="SOXL", amount=1.0,
                  buy_sell="Buy", order_type="Market", price=None, status="Working")
    assert order_to_dict(o)["price"] is None


def test_trade_cost_to_dict_includes_break_even_price():
    tc = TradeCost(instrument="SOXL", uic=46780, asset_type="Etf", direction="long",
                   amount=10.0, price=200.0, account_currency="JPY",
                   instrument_currency="USD", total_cost=10.0, total_cost_pct=0.5,
                   is_round_trip=True, commission=2.0, commission_pct=0.1,
                   min_commission=1.0, conversion_cost=1.0, conversion_cost_pct=0.05,
                   conversion_rate_pct=0.25, spread_cost=1.0, spread_pct=0.05,
                   holding_cost=0.0, assumptions=["IncludesOpenAndCloseCost"])
    d = trade_cost_to_dict(tc)
    assert d["total_cost_pct"] == 0.5 and d["is_round_trip"] is True
    # break_even_price() の導出値が payload に含まれる（long: price*(1+pct/100)）
    assert d["break_even_price"] == pytest.approx(200.0 * 1.005)


def test_quote_to_dict_serializes_datetimes_and_summary():
    q = RealtimeQuote(symbol="SOXL", price=165.28, fetched_at=NOW,
                      bar_time_et=datetime(2026, 7, 7, 16, 0, tzinfo=JST),
                      regular_close=194.65, regular_close_date=date(2026, 7, 7),
                      baseline_stale_days=0, delta_pct=-15.06, session="post",
                      source="yfinance", confirm_source="tiingo_iex",
                      confirm_price=165.3, is_thin=True)
    d = quote_to_dict(q)
    assert d["price"] == 165.28 and d["session"] == "post" and d["is_thin"] is True
    # datetime は JSON 化のため isoformat 文字列
    assert d["fetched_at"] == NOW.isoformat()
    assert isinstance(d["bar_time_et"], str)
    assert "SOXL" in d["summary"]
    # 乖離%の基準がいつのものかを読み手が検算できる (ADR-031)
    assert d["regular_close_date"] == "2026-07-07"
    assert d["baseline_stale_days"] == 0


def test_quote_to_dict_carries_stale_baseline_marker():
    # 基準が stale の時は delta_pct が None のまま JSON に出る (null)。
    # 古い終値との乖離%を現値の動きと誤読させないため (ADR-031)。
    q = RealtimeQuote(symbol="SOXL", price=112.36, fetched_at=NOW,
                      bar_time_et=datetime(2026, 8, 31, 18, 50, tzinfo=JST),
                      regular_close=116.60, regular_close_date=date(2026, 8, 26),
                      baseline_stale_days=2, delta_pct=None, session="pre",
                      source="yfinance", confirm_source=None,
                      confirm_price=None, is_thin=True)
    d = quote_to_dict(q)
    assert d["delta_pct"] is None
    assert d["regular_close_date"] == "2026-08-26"
    assert d["baseline_stale_days"] == 2
    assert "update_data.py" in d["summary"]


# ── decide_mode: read_only / read_write / auth_required の分岐（純関数） ──

def test_decide_mode_auth_required_when_no_refresh():
    assert decide_mode(None, None, NOW) == "auth_required"


def test_decide_mode_read_only_when_access_has_buffer():
    access = {"expires_at": NOW + timedelta(minutes=10)}
    refresh = {"expires_at": NOW + timedelta(hours=1)}
    assert decide_mode(access, refresh, NOW) == "read_only"


def test_decide_mode_read_write_when_access_within_buffer():
    # buffer(60s)以内 → refresh(書き込み)が要るので read_write
    access = {"expires_at": NOW + timedelta(seconds=30)}
    refresh = {"expires_at": NOW + timedelta(hours=1)}
    assert decide_mode(access, refresh, NOW) == "read_write"


def test_decide_mode_read_write_when_no_access_but_refresh():
    assert decide_mode(None, {"expires_at": NOW + timedelta(hours=1)}, NOW) == "read_write"


# ── _retry_on_lock: ロック競合(IOException)をバックオフ吸収 ──

def test_retry_on_lock_succeeds_after_transient():
    calls = {"n": 0}
    slept: list[float] = []

    def thunk():
        calls["n"] += 1
        if calls["n"] < 3:
            raise duckdb.IOException("Could not set lock on file")
        return "ok"

    out = _retry_on_lock(thunk, sleep=slept.append, attempts=4, base_backoff=0.1)
    assert out == "ok"
    assert calls["n"] == 3
    assert len(slept) == 2  # 2回リトライ待ち


def test_retry_on_lock_reraises_after_exhaustion():
    def thunk():
        raise duckdb.IOException("locked")

    with pytest.raises(duckdb.IOException):
        _retry_on_lock(thunk, sleep=lambda _s: None, attempts=2, base_backoff=0.0)


# ── payload 関数: serialize と AUTH_REQUIRED 構造化エラーの配線 ──

class _FakeClient:
    def __init__(self, *, balances=None, positions=None, orders=None):
        self._balances = balances or []
        self._positions = positions or []
        self._orders = orders or []

    def get_all_account_balances(self):
        return self._balances

    def get_live_positions(self):
        return self._positions

    def get_open_orders(self):
        return self._orders


def test_account_balances_serializes(monkeypatch):
    fake = _FakeClient(balances=[_balance()])
    monkeypatch.setattr(live_reads, "read_live", lambda op, **k: op(fake))
    out = live_reads.account_balances()
    assert out["accounts"][0]["spending_power"] == 79957.0


def test_positions_serializes(monkeypatch):
    p = LivePosition(account_id="a", uic=46780, symbol="SOXL", amount=13.0,
                     open_price=189.9, unrealized_pnl_base=-49968.0)
    monkeypatch.setattr(live_reads, "read_live", lambda op, **k: op(_FakeClient(positions=[p])))
    out = live_reads.positions()
    assert out["positions"][0]["amount"] == 13.0


def test_auth_required_maps_to_structured_error(monkeypatch):
    def boom(op, **k):
        raise AuthRequired("No valid Saxo refresh token")

    monkeypatch.setattr(live_reads, "read_live", boom)
    out = live_reads.account_balances()
    assert out["error"] == "AUTH_REQUIRED"
    assert "message" in out and "remedy" in out


def test_trade_cost_unknown_symbol_returns_error():
    out = live_reads.trade_cost("NVDA", amount=1, price=100.0)
    assert out["error"] == "UNKNOWN_SYMBOL"


def test_realtime_quote_no_baseline(monkeypatch):
    def boom(symbol):
        raise RuntimeError(f"{symbol}: parquet 日足が空。regular_close を決定できない")

    monkeypatch.setattr(live_reads, "fetch_realtime_quote", boom)
    out = live_reads.realtime_quote("JPY=X")
    assert out["error"] == "NO_BASELINE"


def test_realtime_quote_happy(monkeypatch):
    q = RealtimeQuote(symbol="SOXL", price=165.28, fetched_at=NOW,
                      bar_time_et=NOW, regular_close=194.65,
                      regular_close_date=date(2026, 7, 7), baseline_stale_days=0,
                      delta_pct=-15.06,
                      session="post", source="yfinance", confirm_source=None,
                      confirm_price=None, is_thin=True)
    monkeypatch.setattr(live_reads, "fetch_realtime_quote", lambda s: q)
    out = live_reads.realtime_quote("SOXL")
    assert out["price"] == 165.28 and out["symbol"] == "SOXL"
