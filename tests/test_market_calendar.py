"""NYSE 営業日カレンダーのテスト。

祝日を知らない営業日計算は、祝日翌日に「データが1日古い」と誤検知し、更新しても
消えない警告を出す (ADR-031 の stale 検知が自壊する)。その回帰を防ぐ。
testing-guidelines.md (ADR-022) の4層 (既知解/境界/不変量/反例) に沿う。
"""
from datetime import date, timedelta

import pytest

from src.market_calendar import (
    _easter_sunday,
    is_trading_day,
    nyse_holidays,
    previous_trading_day,
    trading_days_between,
)


# ── 既知解: 外部で検算できる実日付 ───────────────────────────────


class TestKnownHolidays:
    @pytest.mark.parametrize(
        "d,label",
        [
            (date(2026, 1, 1), "元日 (木)"),
            (date(2026, 1, 19), "キング牧師記念日 (第3月)"),
            (date(2026, 2, 16), "大統領の日 (第3月)"),
            (date(2026, 4, 3), "グッドフライデー (復活祭 4/5 の2日前)"),
            (date(2026, 5, 25), "メモリアルデー (最終月)"),
            (date(2026, 6, 19), "ジューンティーンス (金)"),
            (date(2026, 7, 3), "独立記念日 7/4(土) の振替 → 前金曜"),
            (date(2026, 9, 7), "レイバーデー (第1月)"),
            (date(2026, 11, 26), "感謝祭 (第4木)"),
            (date(2026, 12, 25), "クリスマス (金)"),
        ],
    )
    def test_2026_holidays(self, d, label):
        assert d in nyse_holidays(2026), label
        assert is_trading_day(d) is False, label

    def test_2026_holiday_count(self):
        # 2026年は振替が重ならないので10日 (Juneteenth 含む)
        assert len(nyse_holidays(2026)) == 10

    @pytest.mark.parametrize(
        "year,expected",
        [
            (2024, date(2024, 3, 31)),
            (2025, date(2025, 4, 20)),
            (2026, date(2026, 4, 5)),
            (2027, date(2027, 3, 28)),
        ],
    )
    def test_easter_sunday_known_values(self, year, expected):
        assert _easter_sunday(year) == expected


# ── 境界: 振替規則 ───────────────────────────────────────────────


class TestObservanceRules:
    def test_saturday_holiday_observed_on_friday(self):
        # 2026-07-04 は土曜 → 前金曜 7/3 が休場、7/4 自体は「休場日」ではない
        assert date(2026, 7, 3) in nyse_holidays(2026)
        assert date(2026, 7, 4) not in nyse_holidays(2026)

    def test_sunday_holiday_observed_on_monday(self):
        # 2027-07-04 は日曜 → 翌月曜 7/5 が休場
        assert date(2027, 7, 5) in nyse_holidays(2027)

    def test_juneteenth_not_a_holiday_before_2022(self):
        # NYSE が休場にしたのは 2022年から
        assert date(2021, 6, 18) not in nyse_holidays(2021)
        assert date(2021, 6, 21) not in nyse_holidays(2021)


# ── 臨時休場: 規則で導けない実績 ─────────────────────────────────


class TestAdHocClosures:
    def test_carter_day_of_mourning(self):
        # 2025-01-09 (木) は国葬で休場。規則からは導けないので実績で持つ。
        # SPY 日足 parquet と突合して見つけた唯一の乖離。
        assert is_trading_day(date(2025, 1, 9)) is False

    def test_hurricane_sandy(self):
        assert is_trading_day(date(2012, 10, 29)) is False
        assert is_trading_day(date(2012, 10, 30)) is False

    def test_previous_trading_day_skips_ad_hoc_closure(self):
        # 2025-01-10(金) の前営業日は、国葬(1/9)を飛ばして 1/8(水)
        assert previous_trading_day(date(2025, 1, 10)) == date(2025, 1, 8)


# ── is_trading_day / previous_trading_day ────────────────────────


class TestTradingDay:
    def test_ordinary_weekday_is_trading_day(self):
        assert is_trading_day(date(2026, 8, 28)) is True  # 金

    def test_weekend_is_not_trading_day(self):
        assert is_trading_day(date(2026, 8, 29)) is False  # 土
        assert is_trading_day(date(2026, 8, 30)) is False  # 日

    def test_previous_trading_day_skips_weekend(self):
        # 月(8/31) の前営業日は金(8/28)
        assert previous_trading_day(date(2026, 8, 31)) == date(2026, 8, 28)

    def test_previous_trading_day_skips_holiday_and_weekend(self):
        # 火(9/8) の前営業日は、レイバーデー(9/7)と週末を飛ばして金(9/4)
        assert previous_trading_day(date(2026, 9, 8)) == date(2026, 9, 4)

    def test_previous_trading_day_crosses_year_boundary(self):
        # 2026-01-01(元日) は休場 → 2025-12-31(水) まで戻る
        assert previous_trading_day(date(2026, 1, 2)) == date(2025, 12, 31)


# ── trading_days_between: 不変量 + 実インシデント ────────────────


class TestTradingDaysBetween:
    def test_consecutive_trading_days(self):
        assert trading_days_between(date(2026, 8, 27), date(2026, 8, 28)) == 1

    def test_same_day_is_zero(self):
        assert trading_days_between(date(2026, 8, 28), date(2026, 8, 28)) == 0

    def test_end_before_start_is_zero(self):
        assert trading_days_between(date(2026, 8, 28), date(2026, 8, 26)) == 0

    def test_weekend_not_counted(self):
        assert trading_days_between(date(2026, 8, 28), date(2026, 8, 31)) == 1

    def test_holiday_not_counted(self):
        # 金(9/4) → 火(9/8) は、レイバーデー(9/7)を挟むので営業日1日ぶん。
        # 祝日を数えると 2 になり、更新済みのデータを「1日古い」と誤検知する。
        assert trading_days_between(date(2026, 9, 4), date(2026, 9, 8)) == 1

    def test_matches_actual_incident(self):
        # 2026-08-26(水) の終値を 08-28(金) の終値と誤認した実インシデント
        assert trading_days_between(date(2026, 8, 26), date(2026, 8, 28)) == 2

    def test_monotonic_over_a_week(self):
        # 不変量: 終点を後ろにずらすと単調非減少
        start = date(2026, 8, 24)
        counts = [trading_days_between(start, start + timedelta(days=k)) for k in range(0, 15)]
        assert counts == sorted(counts)
