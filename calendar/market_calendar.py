"""米株(NYSE/Nasdaq) 休場・早引け判定ヘルパー.

Source of Truth は同ディレクトリの us_market_holidays.ics(NYSE公式由来・検証済)。
Google Calendar もこの .ics を購読しているので、人間の閲覧と Claude の判定が同一データを見る。
外部API・認証・MCP に一切依存しない(CLAUDE.md「SoTはリポジトリ内」原則)。

当日ワークフローでの用途:
    from datetime import date
    if not market_calendar.is_market_open(today):
        # 休場 -> update_data/scan をスキップ、次営業日を提示
公式仕様: docs 外部だが NYSE 公式(2026-2028 Holiday and Early Closings Calendar)を転記。

カバレッジ範囲外の日付は誤答を防ぐため ValueError を投げる(黙って open を返さない)。
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

_ICS_PATH = Path(__file__).parent / "us_market_holidays.ics"

_CAT_TO_KIND = {"Market Holiday": "holiday", "Market Early Close": "early"}


@lru_cache(maxsize=1)
def _load() -> tuple[dict[date, str], tuple[int, int]]:
    """.ics をパースして {date: 'holiday'|'early'} と (min_year, max_year) を返す."""
    text = _ICS_PATH.read_text(encoding="utf-8")
    table: dict[date, str] = {}
    for block in text.split("BEGIN:VEVENT")[1:]:
        m_date = re.search(r"DTSTART[^:]*:(\d{8})", block)
        m_cat = re.search(r"CATEGORIES:(.+)", block)
        if not (m_date and m_cat):
            continue
        d = m_date.group(1)
        kind = _CAT_TO_KIND.get(m_cat.group(1).strip())
        if kind is None:
            continue
        table[date(int(d[:4]), int(d[4:6]), int(d[6:8]))] = kind
    if not table:
        raise RuntimeError(f"市場休場データが空: {_ICS_PATH}")
    years = tuple(y for y in (min(d.year for d in table), max(d.year for d in table)))
    return table, years


def coverage_years() -> tuple[int, int]:
    """データが網羅する (最小年, 最大年)."""
    _, years = _load()
    return years


def _check_range(d: date) -> None:
    lo, hi = coverage_years()
    if not (lo <= d.year <= hi):
        raise ValueError(
            f"{d} はデータ範囲外({lo}-{hi})。generate_holidays_ics.py に年を追加して再生成すること"
        )


def is_market_holiday(d: date) -> bool:
    """終日休場(祝日クローズ)なら True。早引け日・週末は False。"""
    _check_range(d)
    table, _ = _load()
    return table.get(d) == "holiday"


def is_early_close(d: date) -> bool:
    """13:00 ET 短縮取引日なら True。"""
    _check_range(d)
    table, _ = _load()
    return table.get(d) == "early"


def market_status(d: date) -> str:
    """'holiday' | 'early_close' | 'weekend' | 'open' を返す。"""
    _check_range(d)
    table, _ = _load()
    kind = table.get(d)
    if kind == "holiday":
        return "holiday"
    if kind == "early":
        return "early_close"
    if d.weekday() >= 5:
        return "weekend"
    return "open"


def is_market_open(d: date) -> bool:
    """その日に通常/短縮でも取引があるなら True(早引け日も開場扱い)。"""
    return market_status(d) in ("open", "early_close")


def next_trading_day(d: date) -> date:
    """d の翌日以降で最初の取引日(早引け日も含む)を返す。"""
    nxt = d + timedelta(days=1)
    while not is_market_open(nxt):
        nxt += timedelta(days=1)
    return nxt


def describe(d: date) -> str:
    """人間可読の1行サマリ。"""
    st = market_status(d)
    label = {
        "holiday": "米株 終日休場",
        "early_close": "米株 13:00 ET 早引け",
        "weekend": "週末(米株休場)",
        "open": "米株 通常営業日",
    }[st]
    if st in ("holiday", "weekend"):
        return f"{d.isoformat()} ({d.strftime('%a')}): {label} / 次の取引日 {next_trading_day(d).isoformat()}"
    return f"{d.isoformat()} ({d.strftime('%a')}): {label}"


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    else:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.db import today_jst  # date.today() 禁止(CLAUDE.md) — JST基準

        target = today_jst()
    print(describe(target))
