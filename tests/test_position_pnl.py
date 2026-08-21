"""scripts/position_pnl.py の純粋ロジック (format_line) のテスト。

I/O (Saxo API, yfinance, realtime quote) はテスト対象外。
通知欄に載る文言の不変条件だけを検証する:
  - 含み損益が先頭にあり、ドル額と % が必ず併記される (CLAUDE.md Rules)
  - 為替が取れない時は円換算を出さない (推測値を通知欄に出さない)
  - 薄商い (pre/post) は明示される (ADR-031)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.position_pnl import format_line


def _snap(**overrides) -> dict:
    base = dict(
        symbol="SOXL",
        quantity=25.0,
        entry_price=119.879,
        price=126.14,
        session="pre",
        is_thin=True,
        regular_close=122.21,
        delta_pct_vs_close=3.21,
        bar_time_et="2026-08-21T05:44:00-04:00",
        fetched_at="2026-08-21T18:44:00+09:00",
        pnl_usd=156.525,
        entry_cost_usd=2996.975,
        entry_pct=5.222,
        pnl_jpy=24814.0,
        acct_total_jpy=538648.1,
        acct_pct=4.607,
        usdjpy=158.53,
    )
    base.update(overrides)
    return base


def test_profit_shows_dollar_and_percent_together():
    line = format_line(_snap())
    assert line.startswith("SOXL 含み +157$")
    assert "+5.22%" in line
    assert "+24,814円" in line
    assert "口座+4.61%" in line


def test_loss_keeps_sign_and_percent():
    line = format_line(_snap(pnl_usd=-240.0, entry_pct=-8.0,
                             pnl_jpy=-38000.0, acct_pct=-7.05))
    assert "-240$" in line
    assert "-8.00%" in line
    assert "-38,000円" in line
    assert "口座-7.05%" in line


def test_no_yen_when_fx_unavailable():
    """為替が取れない時は円換算を出さない(推測値を通知欄に出さない)。"""
    line = format_line(_snap(pnl_jpy=None, acct_pct=None, usdjpy=None))
    assert "円" not in line
    assert "口座" not in line
    assert "+157$" in line
    assert "+5.22%" in line


def test_thin_session_is_flagged():
    assert "(薄商い)" in format_line(_snap(is_thin=True))
    assert "(薄商い)" not in format_line(_snap(is_thin=False, session="regular"))


def test_price_and_entry_present():
    line = format_line(_snap())
    assert "現値$126.14" in line
    assert "建値$119.879" in line
    assert "25株" in line
