"""tiingo_client のシンボルユニバース定義のテスト (ADR-004 / ADR-032)。

参照指数 (取引しない 1x ETF) の蓄積方針を回帰ガードする (ADR-032):
- VIXY/TECS: 低流動性のため日足のみ。
- SOXX/SPY/QQQ/IWM: 高流動性の de-levered 参照。日足 + 5分足を蓄積。
  (各々に売買する 3x 対応あり: SOXX→SOXL/SOXS, QQQ→TQQQ/SQQQ, SPY→SPXL, IWM→TNA/TZA)

intraday ループ (update_data.update_intraday) は INTRADAY_SYMBOLS を走査する。
取引銘柄でない参照指数を 5分足蓄積させるには INTRADAY_SYMBOLS に含める必要がある。
"""

from src.tiingo_client import (
    TRADING_SYMBOLS,
    REFERENCE_SYMBOLS,
    REFERENCE_SYMBOLS_DAILY_ONLY,
    REFERENCE_SYMBOLS_INTRADAY,
    ALL_SYMBOLS,
    INTRADAY_SYMBOLS,
)

# ADR-032 で追加した de-levered 参照指数 (原指数の素の強弱を読むため)
DELEVERED_REFERENCES = ["SOXX", "SPY", "QQQ", "IWM"]


def test_delevered_references_are_registered():
    """SOXX/SPY/QQQ/IWM が参照銘柄として登録されている (ADR-032)。"""
    for sym in DELEVERED_REFERENCES:
        assert sym in REFERENCE_SYMBOLS, f"{sym} が REFERENCE_SYMBOLS に無い"
        assert sym in REFERENCE_SYMBOLS_INTRADAY, f"{sym} が REFERENCE_SYMBOLS_INTRADAY に無い"


def test_delevered_references_accumulate_intraday_but_not_traded():
    """参照指数は 5分足蓄積するが、取引銘柄ではない (ADR-032)。

    - INTRADAY_SYMBOLS に含まれる → update_intraday が 5分足を蓄積する。
    - TRADING_SYMBOLS に含まれない → ポジション/執行の対象にしない。
    """
    for sym in DELEVERED_REFERENCES:
        assert sym in INTRADAY_SYMBOLS, f"{sym} が INTRADAY_SYMBOLS に無い (5分足が貯まらない)"
        assert sym not in TRADING_SYMBOLS, f"{sym} が TRADING_SYMBOLS に混入 (取引対象になってしまう)"


def test_low_liquidity_references_stay_daily_only():
    """VIXY/TECS は低流動性のため日足のみ (5分足蓄積しない)。"""
    for sym in REFERENCE_SYMBOLS_DAILY_ONLY:
        assert sym in REFERENCE_SYMBOLS, f"{sym} が REFERENCE_SYMBOLS に無い"
        assert sym not in INTRADAY_SYMBOLS, f"{sym} が INTRADAY_SYMBOLS に混入 (日足のみのはず)"
    assert "VIXY" in REFERENCE_SYMBOLS_DAILY_ONLY
    assert "TECS" in REFERENCE_SYMBOLS_DAILY_ONLY


def test_symbol_lists_are_consistent_and_deduplicated():
    """各リストの結合関係と重複なしを保証する。"""
    assert REFERENCE_SYMBOLS == REFERENCE_SYMBOLS_DAILY_ONLY + REFERENCE_SYMBOLS_INTRADAY
    assert ALL_SYMBOLS == TRADING_SYMBOLS + REFERENCE_SYMBOLS
    assert INTRADAY_SYMBOLS == TRADING_SYMBOLS + REFERENCE_SYMBOLS_INTRADAY
    assert len(ALL_SYMBOLS) == len(set(ALL_SYMBOLS)), "ALL_SYMBOLS に重複がある"
    assert len(INTRADAY_SYMBOLS) == len(set(INTRADAY_SYMBOLS)), "INTRADAY_SYMBOLS に重複がある"
