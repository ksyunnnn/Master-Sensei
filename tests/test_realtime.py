"""延長時間リアルタイム価格ヘルパーのテスト (ADR-031)。

外部API非依存: PriceSource を Fake で差し替え、now/regular_close を注入する。
testing-guidelines.md (ADR-022) の4層 (既知解/境界/不変量/反例) に沿う。
"""
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.realtime import (
    ET,
    JST,
    ExtendedBar,
    RealtimeQuote,
    classify_session,
    get_realtime_quote,
    latest_regular_close_date,
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


# ── latest_regular_close_date: 既知解 + 境界 ─────────────────────
#
# 「その時点で確定しているレギュラー終値の日付」= 乖離%の基準として正しい日付。
# 2026-06-01(月) 〜 06-07(日) を基準週として使う。


class TestLatestRegularCloseDate:
    def test_after_close_returns_same_day(self):
        # 火 17:00 ET は当日の引け後 → 当日の終値が確定済み
        assert latest_regular_close_date(et(2026, 6, 2, 17, 0)) == date(2026, 6, 2)

    def test_before_close_returns_previous_day(self):
        # 火 06:00 ET (プレ) は当日の引け前 → 基準は前営業日 (月)
        assert latest_regular_close_date(et(2026, 6, 2, 6, 0)) == date(2026, 6, 1)

    @pytest.mark.parametrize(
        "h,mi,expected",
        [
            (15, 59, date(2026, 6, 1)),  # 引け1分前: まだ当日終値は確定していない
            (16, 0, date(2026, 6, 2)),   # 引け丁度: 当日終値が確定 (境界を含む)
        ],
    )
    def test_close_boundary(self, h, mi, expected):
        assert latest_regular_close_date(et(2026, 6, 2, h, mi)) == expected

    def test_monday_premarket_skips_back_over_weekend(self):
        # 月 06:00 ET → 日曜へ巻き戻り → さらに金曜まで戻る (今回のバグの時間帯)
        assert latest_regular_close_date(et(2026, 6, 8, 6, 0)) == date(2026, 6, 5)

    def test_saturday_returns_friday(self):
        assert latest_regular_close_date(et(2026, 6, 6, 12, 0)) == date(2026, 6, 5)

    def test_sunday_returns_friday(self):
        assert latest_regular_close_date(et(2026, 6, 7, 12, 0)) == date(2026, 6, 5)

    def test_holiday_is_skipped(self):
        # 2026-09-07 はレイバーデー。9/8(火) プレの基準は 9/7 ではなく 9/4(金)。
        # 9/7 を期待してしまうと、存在しない日の終値を待つ警告が出続ける。
        assert latest_regular_close_date(et(2026, 9, 8, 6, 0)) == date(2026, 9, 4)

    def test_holiday_itself_falls_back_to_previous_trading_day(self):
        # 祝日当日の引け後でも、その日の終値は存在しない
        assert latest_regular_close_date(et(2026, 9, 7, 17, 0)) == date(2026, 9, 4)

    def test_naive_datetime_rejected(self):
        with pytest.raises(ValueError):
            latest_regular_close_date(datetime(2026, 6, 2, 17, 0))


# ── get_realtime_quote: 既知解 ───────────────────────────────────


class TestQuoteHappyPath:
    def test_premarket_quote_with_confirm(self):
        now = datetime(2026, 6, 3, 21, 30, tzinfo=JST)  # 08:30 ET = pre
        primary = FakeSource("yfinance", ExtendedBar(281.00, et(2026, 6, 3, 8, 29), None))
        confirm = FakeSource("tiingo_iex", ExtendedBar(280.50, et(2026, 6, 3, 8, 25), 1500))
        q = get_realtime_quote(
            "SOXL",
            regular_close=266.32,
            regular_close_date=date(2026, 6, 2),
            primary=primary,
            confirm=confirm,
            now=now,
        )
        assert q.symbol == "SOXL"
        assert q.price == 281.00
        assert q.session == "pre"
        assert q.source == "yfinance"
        assert q.confirm_source == "tiingo_iex"
        assert q.confirm_price == 280.50
        assert q.regular_close == 266.32
        assert q.regular_close_date == date(2026, 6, 2)
        assert q.baseline_stale_days == 0
        # delta = (281 - 266.32)/266.32 * 100
        assert q.delta_pct == pytest.approx((281.0 - 266.32) / 266.32 * 100, abs=1e-6)
        assert q.fetched_at == now

    def test_regular_session_not_thin(self):
        now = datetime(2026, 6, 2, 23, 0, tzinfo=JST)  # 10:00 ET = regular
        primary = FakeSource("yfinance", ExtendedBar(250.0, et(2026, 6, 2, 9, 59), 10000))
        q = get_realtime_quote(
            "SOXL",
            regular_close=240.0,
            regular_close_date=date(2026, 6, 1),
            primary=primary,
            confirm=None,
            now=now,
        )
        assert q.session == "regular"
        assert q.is_thin is False


# ── 基準足の鮮度: 今回のバグの回帰テスト ─────────────────────────
#
# 現値を realtime に差し替えても、比較の相手 (parquet 終値) が stale なら
# 乖離%は無意味になる。ADR-031 の目的は「stale を黙って使わせない」なので、
# 基準が古い時は delta_pct を None にして誤読の源そのものを消す。


class TestStaleBaseline:
    def _quote(self, regular_close, regular_close_date, price=112.36):
        # 2026-08-31(月) 05:50 ET = pre。基準として正しいのは 08-28(金) の終値。
        now = datetime(2026, 8, 31, 18, 50, tzinfo=JST)
        primary = FakeSource("yfinance", ExtendedBar(price, et(2026, 8, 31, 5, 50), None))
        return get_realtime_quote(
            "SOXL",
            regular_close=regular_close,
            regular_close_date=regular_close_date,
            primary=primary,
            confirm=None,
            now=now,
        )

    def test_fresh_baseline_computes_delta(self):
        q = self._quote(111.34, date(2026, 8, 28))
        assert q.baseline_stale_days == 0
        assert q.delta_pct == pytest.approx((112.36 - 111.34) / 111.34 * 100, abs=1e-6)

    def test_stale_baseline_suppresses_delta(self):
        # 実インシデント: 8/26 の終値 $116.60 を基準に -3.64% と表示し、
        # 「週末をまたいで戻した」と読ませた。正しくは 8/28 $111.34 比 +0.92%。
        q = self._quote(116.60, date(2026, 8, 26))
        assert q.baseline_stale_days == 2
        assert q.delta_pct is None

    def test_stale_baseline_still_returns_price(self):
        # 現値そのものは正しく取れているので返す (取得を止めない)
        q = self._quote(116.60, date(2026, 8, 26))
        assert q.price == 112.36
        assert q.session == "pre"
        assert q.regular_close == 116.60

    def test_stale_summary_names_the_date_and_omits_delta(self):
        q = self._quote(116.60, date(2026, 8, 26))
        s = q.summary()
        assert "08-26" in s          # 基準がいつのものか必ず名指しする
        assert "-3.64%" not in s     # 誤読の源だった乖離%は出さない
        assert "update_data.py" in s  # 復旧手段を示す

    def test_fresh_summary_names_the_baseline_date(self):
        # stale でなくても基準日は常に出す (読み手が鮮度を検算できる状態にする)
        q = self._quote(111.34, date(2026, 8, 28))
        assert "08-28" in q.summary()

    def test_baseline_ahead_of_expected_is_not_stale(self):
        # データ側が先行しているケース (期待 8/28 に対し基準 8/31) は stale ではない
        q = self._quote(111.34, date(2026, 8, 31))
        assert q.baseline_stale_days == 0
        assert q.delta_pct is not None

    def test_day_after_holiday_is_not_flagged_stale(self):
        # 2026-09-07 レイバーデー翌日(9/8 火)のプレ。最新データは 9/4(金) の終値で、
        # それが正しい状態。祝日を数えると「1日古い」と誤検知し、update_data.py を
        # 実行しても消えない警告が出続ける (警告を無視する習慣を作る)。
        now = datetime(2026, 9, 8, 19, 0, tzinfo=JST)
        primary = FakeSource("yfinance", ExtendedBar(120.0, et(2026, 9, 8, 6, 0), None))
        q = get_realtime_quote(
            "SOXL",
            regular_close=118.0,
            regular_close_date=date(2026, 9, 4),
            primary=primary,
            confirm=None,
            now=now,
        )
        assert q.baseline_stale_days == 0
        assert q.delta_pct == pytest.approx((120.0 - 118.0) / 118.0 * 100, abs=1e-6)


# ── is_thin: 反例/不変量 ─────────────────────────────────────────


class TestThinLogic:
    def _quote(self, now, vol, confirm):
        primary = FakeSource("yfinance", ExtendedBar(281.0, now.astimezone(ET), vol))
        c = FakeSource("tiingo", ExtendedBar(280.0, now.astimezone(ET), 100)) if confirm else None
        return get_realtime_quote(
            "SOXL",
            regular_close=266.32,
            regular_close_date=latest_regular_close_date(now.astimezone(ET)),
            primary=primary,
            confirm=c,
            now=now,
        )

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
            get_realtime_quote(
                "SOXL",
                regular_close=266.32,
                regular_close_date=date(2026, 6, 2),
                primary=primary,
                confirm=None,
                now=now,
            )

    def test_confirm_failure_degrades_gracefully(self):
        # 裏取りソースが例外でも、主ソースの現値は返る (confirm は None になる)
        now = datetime(2026, 6, 3, 21, 30, tzinfo=JST)
        primary = FakeSource("yfinance", ExtendedBar(281.0, et(2026, 6, 3, 8, 29), None))
        confirm = FakeSource("tiingo", RuntimeError("api down"))
        q = get_realtime_quote(
            "SOXL",
            regular_close=266.32,
            regular_close_date=date(2026, 6, 2),
            primary=primary,
            confirm=confirm,
            now=now,
        )
        assert q.price == 281.0
        assert q.confirm_source is None
        assert q.confirm_price is None

    def test_delta_sign_negative_when_below_close(self):
        now = datetime(2026, 6, 3, 21, 30, tzinfo=JST)
        primary = FakeSource("yfinance", ExtendedBar(250.0, et(2026, 6, 3, 8, 29), None))
        q = get_realtime_quote(
            "SOXL",
            regular_close=266.32,
            regular_close_date=date(2026, 6, 2),
            primary=primary,
            confirm=None,
            now=now,
        )
        assert q.delta_pct < 0
