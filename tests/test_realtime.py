"""延長時間リアルタイム価格ヘルパーのテスト (ADR-031)。

外部API非依存: PriceSource を Fake で差し替え、now/regular_close を注入する。
testing-guidelines.md (ADR-022) の4層 (既知解/境界/不変量/反例) に沿う。
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.realtime import (
    ET,
    JST,
    ExtendedBar,
    RealtimeQuote,
    classify_session,
    get_realtime_quote,
)


def et(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=ET)


class FakeSource:
    """PriceSource 模擬。fetch_latest_extended が固定値 or None or 例外を返す。"""

    def __init__(self, name, result):
        self.name = name
        self._result = result

    def fetch_latest_extended(self, symbol):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


# ── classify_session: 既知解 + 境界 ──────────────────────────────


class TestClassifySession:
    def test_regular_midday(self):
        assert classify_session(et(2026, 6, 2, 12, 0)) == "regular"

    def test_premarket(self):
        assert classify_session(et(2026, 6, 2, 6, 30)) == "pre"

    def test_postmarket(self):
        assert classify_session(et(2026, 6, 2, 17, 0)) == "post"

    def test_overnight_closed(self):
        assert classify_session(et(2026, 6, 2, 2, 0)) == "closed"

    @pytest.mark.parametrize(
        "h,mi,expected",
        [
            (4, 0, "pre"),       # プレ開始の下限 (含む)
            (9, 29, "pre"),      # 寄り直前
            (9, 30, "regular"),  # 寄り (含む)
            (15, 59, "regular"), # 引け直前
            (16, 0, "post"),     # 引け = アフター開始 (含む)
            (19, 59, "post"),    # アフター終了直前
            (20, 0, "closed"),   # アフター終了 (含まない)
            (3, 59, "closed"),   # プレ開始直前
        ],
    )
    def test_boundaries(self, h, mi, expected):
        assert classify_session(et(2026, 6, 2, h, mi)) == expected

    def test_weekend_closed_even_in_regular_hours(self):
        # 2026-06-06 は土曜
        assert classify_session(et(2026, 6, 6, 12, 0)) == "closed"

    def test_naive_datetime_rejected(self):
        with pytest.raises(ValueError):
            classify_session(datetime(2026, 6, 2, 12, 0))


# ── get_realtime_quote: 既知解 ───────────────────────────────────


class TestQuoteHappyPath:
    def test_premarket_quote_with_confirm(self):
        now = datetime(2026, 6, 3, 21, 30, tzinfo=JST)  # 08:30 ET = pre
        primary = FakeSource("yfinance", ExtendedBar(281.00, et(2026, 6, 3, 8, 29), None))
        confirm = FakeSource("tiingo_iex", ExtendedBar(280.50, et(2026, 6, 3, 8, 25), 1500))
        q = get_realtime_quote(
            "SOXL", regular_close=266.32, primary=primary, confirm=confirm, now=now
        )
        assert q.symbol == "SOXL"
        assert q.price == 281.00
        assert q.session == "pre"
        assert q.source == "yfinance"
        assert q.confirm_source == "tiingo_iex"
        assert q.confirm_price == 280.50
        assert q.regular_close == 266.32
        # delta = (281 - 266.32)/266.32 * 100
        assert q.delta_pct == pytest.approx((281.0 - 266.32) / 266.32 * 100, abs=1e-6)
        assert q.fetched_at == now

    def test_regular_session_not_thin(self):
        now = datetime(2026, 6, 2, 23, 0, tzinfo=JST)  # 10:00 ET = regular
        primary = FakeSource("yfinance", ExtendedBar(250.0, et(2026, 6, 2, 9, 59), 10000))
        q = get_realtime_quote(
            "SOXL", regular_close=240.0, primary=primary, confirm=None, now=now
        )
        assert q.session == "regular"
        assert q.is_thin is False


# ── is_thin: 反例/不変量 ─────────────────────────────────────────


class TestThinLogic:
    def _quote(self, now, vol, confirm):
        primary = FakeSource("yfinance", ExtendedBar(281.0, now.astimezone(ET), vol))
        c = FakeSource("tiingo", ExtendedBar(280.0, now.astimezone(ET), 100)) if confirm else None
        return get_realtime_quote("SOXL", regular_close=266.32, primary=primary, confirm=c, now=now)

    def test_premarket_is_thin(self):
        # 08:30 ET pre は確認ありでも extended=thin (froth 注意は常に立てる)
        now = datetime(2026, 6, 3, 21, 30, tzinfo=JST)
        assert self._quote(now, 1000, confirm=True).is_thin is True

    def test_postmarket_is_thin(self):
        now = datetime(2026, 6, 3, 6, 0, tzinfo=JST)  # 17:00 ET = post
        assert self._quote(now, 1000, confirm=True).is_thin is True

    def test_regular_not_thin(self):
        now = datetime(2026, 6, 2, 23, 0, tzinfo=JST)  # 10:00 ET regular
        assert self._quote(now, 10000, confirm=False).is_thin is False


# ── fallback / 反例 ──────────────────────────────────────────────


class TestFallbackAndErrors:
    def test_primary_none_raises(self):
        # 主ソースが現値を返せない (None) → 取得失敗を明示
        now = datetime(2026, 6, 3, 21, 30, tzinfo=JST)
        primary = FakeSource("yfinance", None)
        with pytest.raises(RuntimeError):
            get_realtime_quote("SOXL", regular_close=266.32, primary=primary, confirm=None, now=now)

    def test_confirm_failure_degrades_gracefully(self):
        # 裏取りソースが例外でも、主ソースの現値は返る (confirm は None になる)
        now = datetime(2026, 6, 3, 21, 30, tzinfo=JST)
        primary = FakeSource("yfinance", ExtendedBar(281.0, et(2026, 6, 3, 8, 29), None))
        confirm = FakeSource("tiingo", RuntimeError("api down"))
        q = get_realtime_quote("SOXL", regular_close=266.32, primary=primary, confirm=confirm, now=now)
        assert q.price == 281.0
        assert q.confirm_source is None
        assert q.confirm_price is None

    def test_delta_sign_negative_when_below_close(self):
        now = datetime(2026, 6, 3, 21, 30, tzinfo=JST)
        primary = FakeSource("yfinance", ExtendedBar(250.0, et(2026, 6, 3, 8, 29), None))
        q = get_realtime_quote("SOXL", regular_close=266.32, primary=primary, confirm=None, now=now)
        assert q.delta_pct < 0
