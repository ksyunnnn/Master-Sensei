"""データ更新CLIツール

Usage:
    python update_data.py                # 全データ更新
    python update_data.py --macro-only   # マクロ指標のみ
    python update_data.py --daily-only   # 日足のみ
    python update_data.py --status       # キャッシュ状態確認（API呼び出しなし）
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from src.fred_client import FredClient
from src.providers import ProviderChain, FredAdapter, YFinanceAdapter, NasdaqAdapter
from src.tiingo_client import TiingoFetcher, TiingoConfig, TRADING_SYMBOLS, REFERENCE_SYMBOLS
from src.cache_manager import CacheManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data" / "parquet"
DAILY_LOOKBACK_YEARS = 5


def _build_provider_chain() -> ProviderChain:
    """ProviderChainを構築する（ADR-006, ADR-009）

    順序: yfinance（速い、VIX/VIX3M/Brent）→ FRED（全9シリーズ、公式）
    NasdaqはAPIキーがあれば中間に挿入。
    """
    providers = [YFinanceAdapter()]

    nasdaq_key = os.environ.get("NASDAQ_API_KEY")
    if nasdaq_key:
        providers.append(NasdaqAdapter(nasdaq_key))

    providers.append(FredAdapter(FredClient.from_env()))
    return ProviderChain(providers)


def update_macro(cache: CacheManager):
    """マクロ9シリーズの差分取得（ADR-009: ProviderChain経由、source列付き）

    ProviderChainがyfinance→FREDの順に試行し、最初に成功したソースを使う。
    取得した値はsource列付きでParquetに保存する。
    """
    chain = _build_provider_chain()
    today = date.today()

    for name in sorted(chain.available_series()):
        meta = cache.get_macro_metadata(name)
        if meta:
            start = meta.end_date
        else:
            start = today - timedelta(days=365)

        logger.info(f"{name}: fetching {start} → {today}")
        try:
            records, source = chain.fetch(name, start, today)
        except RuntimeError as e:
            logger.warning(f"{name}: all providers failed: {e}")
            continue

        if not records:
            logger.info(f"{name}: no new data")
            continue

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        cache.save_macro(name, df, source=source)
        logger.info(f"{name}: saved {len(df)} records from {source}")


def update_daily(cache: CacheManager):
    """Tiingo日足の差分取得

    日足は市場閉場後に確定する。end_date >= todayならスキップ。
    閉場前に実行しても当日の確定値はまだないため、翌日に取得される。
    """
    config = TiingoConfig.from_env()
    fetcher = TiingoFetcher(config)
    today = date.today()
    all_symbols = TRADING_SYMBOLS + REFERENCE_SYMBOLS

    for symbol in all_symbols:
        meta = cache._metadata.get(symbol)
        if meta:
            if meta.end_date >= today:
                logger.info(f"{symbol}: daily cache up to date ({meta.end_date})")
                continue
            fetch_start = meta.end_date + timedelta(days=1)
        else:
            fetch_start = today - timedelta(days=365 * DAILY_LOOKBACK_YEARS)

        logger.info(f"{symbol}: fetching daily {fetch_start} → {today}")
        df = fetcher.fetch(symbol, fetch_start, today)

        if not df.empty:
            cache.save_daily(symbol, df, source="tiingo")
            logger.info(f"{symbol}: saved {len(df)} daily bars")


def update_intraday(cache: CacheManager):
    """Tiingo 5分足の差分取得

    5分足は日中に更新される。end_date >= todayでもスキップしない。
    キャッシュ末尾の日付から差分取得し、マージで重複除去。
    これにより日中に複数回実行しても最新の5分足バーを蓄積できる。
    """
    config = TiingoConfig.from_env()
    fetcher = TiingoFetcher(config)
    today = date.today()

    for symbol in TRADING_SYMBOLS:
        meta = cache.get_intraday_metadata(symbol)
        # 5分足は常に差分取得を試みる（日中更新があるため）
        start = (meta.end_date) if meta else None
        logger.info(f"{symbol}: fetching intraday from {start or 'earliest'}")
        df = fetcher.fetch_intraday(symbol, start_date=start, end_date=today)

        if not df.empty:
            cache.save_intraday(symbol, df, source="tiingo")
            logger.info(f"{symbol}: saved {len(df)} intraday bars")


def show_status(cache: CacheManager):
    """キャッシュ状態を表示（--status用の詳細表示）"""
    meta = cache.get_all_metadata()
    print("\n=== Master Sensei Data Status ===\n")

    for section, data in meta.items():
        print(f"[{section}]")
        if not data:
            print("  (empty)")
        for name, info in sorted(data.items()):
            print(f"  {name}: {info['start_date']} → {info['end_date']} ({info['row_count']} rows)")
        print()


def _read_last_row(path: Path) -> Optional[pd.DataFrame]:
    """Parquetファイルの最終行を読み取る"""
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if df.empty:
        return None
    return df.iloc[[-1]]


def show_summary(cache: CacheManager):
    """データサマリーを表示（認知負荷を最小化した一覧）"""
    from datetime import datetime as dt
    now = dt.now()
    print(f"\n=== Data Summary (取得: {now.strftime('%Y-%m-%d %H:%M')} JST) ===\n")

    # ── マクロ ──
    # 意味的ペアで並べる（関連指標を横に配置）
    macro_pairs = [
        ("VIX", "VIX3M"),
        ("HY_SPREAD", "US10Y"),
        ("BRENT", "USD_INDEX"),
        ("YIELD_CURVE", "VXN"),
        ("FEDFUNDS", None),
    ]
    print("[マクロ]")
    for left, right in macro_pairs:
        parts = []
        for name in [left, right]:
            if name is None:
                continue
            row = _read_last_row(cache.macro_dir / f"{name}.parquet")
            if row is not None:
                val = row["value"].iloc[0]
                idx = row.index[0]
                d = idx.date() if hasattr(idx, "date") else idx
                parts.append(f"  {name:<12s}{val:>8.2f}  ({d.month}/{d.day:02d})")
            else:
                parts.append(f"  {name:<12s}{'---':>8s}  (---)")
        print("    ".join(parts))
    print()

    # ── 日足 ──
    daily_latest_date = None
    daily_items = []
    all_symbols = sorted(cache._metadata.keys())
    for symbol in all_symbols:
        row = _read_last_row(cache.daily_dir / f"{symbol}.parquet")
        if row is not None:
            close_col = "Close" if "Close" in row.columns else "close"
            close = row[close_col].iloc[0]
            idx = row.index[0]
            d = idx.date() if hasattr(idx, "date") else idx
            if daily_latest_date is None or d > daily_latest_date:
                daily_latest_date = d
            daily_items.append((symbol, close))

    if daily_items:
        d = daily_latest_date
        print(f"[日足 → {d.month}/{d.day:02d}]")
        # 5銘柄ずつ横並び
        for i in range(0, len(daily_items), 5):
            chunk = daily_items[i:i + 5]
            parts = [f"{sym:<5s}{close:>7.2f}" for sym, close in chunk]
            print("  " + "   ".join(parts))
    print()

    # ── 5分足 ──
    intraday_items = []
    intraday_latest_ts = None
    intraday_symbols = sorted(cache._metadata_intraday.keys())
    for symbol in intraday_symbols:
        row = _read_last_row(cache.intraday_dir / f"{symbol}_5min.parquet")
        if row is not None:
            close_col = "Close" if "Close" in row.columns else "close"
            close = row[close_col].iloc[0]
            ts = row.index[0]
            if intraday_latest_ts is None or ts > intraday_latest_ts:
                intraday_latest_ts = ts
            intraday_items.append((symbol, close, ts))

    if intraday_items:
        # タイムスタンプをET表示
        if intraday_latest_ts is not None:
            try:
                et_ts = intraday_latest_ts.tz_convert("US/Eastern")
            except TypeError:
                et_ts = intraday_latest_ts
            header_time = f"{et_ts.month}/{et_ts.day:02d} {et_ts.strftime('%H:%M')} ET"
        else:
            header_time = "---"

        # 全銘柄同一タイムスタンプかチェック
        all_same_ts = len(set(ts for _, _, ts in intraday_items)) == 1

        if all_same_ts:
            print(f"[5分足 → {header_time}]")
            for i in range(0, len(intraday_items), 4):
                chunk = intraday_items[i:i + 4]
                parts = [f"{sym:<5s}{close:>7.2f}" for sym, close, _ in chunk]
                print("  " + "   ".join(parts))
        else:
            print(f"[5分足 → 最新 {header_time}]")
            for i in range(0, len(intraday_items), 4):
                chunk = intraday_items[i:i + 4]
                parts = []
                for sym, close, ts in chunk:
                    try:
                        et = ts.tz_convert("US/Eastern")
                    except TypeError:
                        et = ts
                    parts.append(f"{sym:<5s}{close:>7.2f} ({et.strftime('%H:%M')})")
                print("  " + "   ".join(parts))
    print()

    # ── 鮮度 ──
    macro_dates = []
    for name in cache._metadata_macro:
        meta = cache._metadata_macro[name]
        macro_dates.append(meta.end_date)
    macro_max = max(macro_dates) if macro_dates else None

    daily_max = daily_latest_date
    n_macro = len(cache._metadata_macro)
    n_daily = len(cache._metadata)
    n_intraday = len(cache._metadata_intraday)

    print("[鮮度]")
    macro_str = f"{macro_max.month}/{macro_max.day:02d}" if macro_max else "---"
    daily_str = f"{daily_max.month}/{daily_max.day:02d}" if daily_max else "---"
    if intraday_latest_ts is not None:
        try:
            et_ts = intraday_latest_ts.tz_convert("US/Eastern")
        except TypeError:
            et_ts = intraday_latest_ts
        intraday_str = f"{et_ts.month}/{et_ts.day:02d} {et_ts.strftime('%H:%M')} ET"
    else:
        intraday_str = "---"

    print(f"  マクロ: {n_macro:>2d}系列 最新 {macro_str}    日足: {n_daily:>2d}銘柄 最新 {daily_str}")
    print(f"  5分足: {n_intraday:>2d}銘柄 最新 {intraday_str}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Master Sensei Data Updater")
    parser.add_argument("--macro-only", action="store_true")
    parser.add_argument("--daily-only", action="store_true")
    parser.add_argument("--intraday-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--symbol", type=str, help="Single symbol to update (e.g. SOXL)")
    args = parser.parse_args()

    cache = CacheManager(DATA_DIR)

    if args.status:
        show_status(cache)
        return

    # --symbol: 単一銘柄の5分足のみ高速取得
    if args.symbol:
        symbol = args.symbol.upper()
        logger.info(f"=== Updating {symbol} intraday only ===")
        config = TiingoConfig.from_env()
        fetcher = TiingoFetcher(config)
        meta = cache.get_intraday_metadata(symbol)
        start = (meta.end_date) if meta else None
        df = fetcher.fetch_intraday(symbol, start_date=start, end_date=date.today())
        if not df.empty:
            cache.save_intraday(symbol, df, source="tiingo")
            logger.info(f"{symbol}: saved {len(df)} intraday bars")
            latest = df.iloc[-1]
            print(f"\n{symbol}: ${latest['Close']:.2f} ({df.index[-1]})")
        else:
            logger.info(f"{symbol}: no new data")
        return

    run_all = not (args.macro_only or args.daily_only or args.intraday_only)

    if run_all or args.macro_only:
        logger.info("=== Updating macro data (ProviderChain) ===")
        update_macro(cache)

    if run_all or args.daily_only:
        logger.info("=== Updating daily data (Tiingo) ===")
        update_daily(cache)

    if run_all or args.intraday_only:
        logger.info("=== Updating intraday data (Tiingo) ===")
        update_intraday(cache)

    show_summary(cache)


if __name__ == "__main__":
    main()
