"""market_calendar のテスト (TDD, ADR準拠).

同ディレクトリの市場休場データ(us_market_holidays.ics)を SoT として、
米株(NYSE/Nasdaq)の休場・早引け・次の営業日判定を検証する。
実行: python calendar/test_market_calendar.py  (プレーンassert・pytestでも可)
"""
from datetime import date

import market_calendar as mc


def test_full_holiday():
    assert mc.is_market_holiday(date(2026, 7, 3)) is True   # 独立記念日(振替)
    assert mc.is_market_holiday(date(2027, 7, 5)) is True   # 2027 独立記念日(振替) — 第三者feedに無かった日
    assert mc.is_market_holiday(date(2028, 12, 25)) is True
    assert mc.is_market_holiday(date(2026, 11, 26)) is True  # 感謝祭


def test_not_holiday_regression():
    # CalendarLabs が誤って休場扱いした日 — 実際は開場
    assert mc.is_market_holiday(date(2026, 11, 11)) is False  # Veterans Day
    # 2028/1/1 は土曜で振替なし = 休場エントリー無し(週末で閉まるだけ)
    assert mc.is_market_holiday(date(2028, 1, 1)) is False


def test_early_close():
    assert mc.is_early_close(date(2026, 11, 27)) is True   # 感謝祭翌日
    assert mc.is_early_close(date(2026, 12, 24)) is True   # クリスマスイブ
    assert mc.is_early_close(date(2028, 7, 3)) is True     # 独立記念日前日(月)
    # 早引け日は「休場」ではない
    assert mc.is_market_holiday(date(2026, 11, 27)) is False
    # 通常日は早引けでない
    assert mc.is_early_close(date(2026, 7, 6)) is False


def test_market_status():
    assert mc.market_status(date(2026, 7, 3)) == "holiday"
    assert mc.market_status(date(2026, 11, 27)) == "early_close"
    assert mc.market_status(date(2028, 1, 1)) == "weekend"   # 土曜
    assert mc.market_status(date(2026, 7, 6)) == "open"       # 月曜・通常


def test_is_open():
    assert mc.is_market_open(date(2026, 7, 6)) is True        # 通常営業日
    assert mc.is_market_open(date(2026, 11, 27)) is True      # 早引けでも開場
    assert mc.is_market_open(date(2026, 7, 3)) is False       # 休場
    assert mc.is_market_open(date(2028, 1, 1)) is False       # 週末


def test_next_trading_day():
    # 金曜(7/3休場) -> 土日跳ばして月曜 7/6
    assert mc.next_trading_day(date(2026, 7, 3)) == date(2026, 7, 6)
    # 感謝祭前水曜 11/25 -> 木(感謝祭休場)跳ばし -> 金 11/27(早引けbut開場)
    assert mc.next_trading_day(date(2026, 11, 25)) == date(2026, 11, 27)
    # 通常の木 -> 翌金
    assert mc.next_trading_day(date(2026, 7, 6)) == date(2026, 7, 7)


def test_out_of_range_raises():
    raised = False
    try:
        mc.is_market_holiday(date(2020, 1, 1))
    except ValueError:
        raised = True
    assert raised, "カバレッジ範囲外は ValueError を投げるべき(誤答防止)"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"PASS: {len(fns)} tests")
