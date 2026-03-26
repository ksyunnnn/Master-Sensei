"""データ更新CLIツール

Usage:
    python update_data.py                # 全データ更新
    python update_data.py --macro-only   # マクロ指標のみ
    python update_data.py --daily-only   # 日足のみ
    python update_data.py --status       # キャッシュ状態確認（API呼び出しなし）
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from src.fred_client import FredClient, SERIES_CONFIG
from src.tiingo_client import TiingoFetcher, TiingoConfig, TRADING_SYMBOLS, REFERENCE_SYMBOLS
from src.cache_manager import CacheManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data" / "parquet"
DAILY_LOOKBACK_YEARS = 5


def update_macro(cache: CacheManager):
    """FRED 9シリーズの差分取得"""
    fred = FredClient.from_env()
    today = date.today()

    for name, series_id in SERIES_CONFIG.items():
        meta = cache.get_macro_metadata(name)
        if meta:
            start = meta.end_date + timedelta(days=1)
            if start > today:
                logger.info(f"{name}: already up to date ({meta.end_date})")
                continue
        else:
            start = today - timedelta(days=365)

        logger.info(f"{name} ({series_id}): fetching {start} → {today}")
        records = fred.fetch_series(series_id, start_date=start, end_date=today)

        if not records:
            logger.info(f"{name}: no new data")
            continue

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        cache.save_macro(name, df)
        logger.info(f"{name}: saved {len(df)} new records")


def update_daily(cache: CacheManager):
    """Tiingo日足の差分取得"""
    config = TiingoConfig.from_env()
    fetcher = TiingoFetcher(config)
    today = date.today()
    all_symbols = TRADING_SYMBOLS + REFERENCE_SYMBOLS

    for symbol in all_symbols:
        # 差分取得: キャッシュの末尾から今日までだけ取得する
        # _get_coverageの先頭不足問題（5年分再取得）を回避
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
            cache.save_daily(symbol, df)
            logger.info(f"{symbol}: saved {len(df)} daily bars")


def update_intraday(cache: CacheManager):
    """Tiingo 5分足の差分取得"""
    config = TiingoConfig.from_env()
    fetcher = TiingoFetcher(config)
    today = date.today()

    for symbol in TRADING_SYMBOLS:
        meta = cache.get_intraday_metadata(symbol)
        if meta and meta.end_date >= today:
            logger.info(f"{symbol}: intraday cache up to date")
            continue

        start = (meta.end_date + timedelta(days=1)) if meta else None
        logger.info(f"{symbol}: fetching intraday from {start or 'earliest'}")
        df = fetcher.fetch_intraday(symbol, start_date=start, end_date=today)

        if not df.empty:
            cache.save_intraday(symbol, df)
            logger.info(f"{symbol}: saved {len(df)} intraday bars")


def show_status(cache: CacheManager):
    """キャッシュ状態を表示"""
    meta = cache.get_all_metadata()
    print("\n=== Master Sensei Data Status ===\n")

    for section, data in meta.items():
        print(f"[{section}]")
        if not data:
            print("  (empty)")
        for name, info in sorted(data.items()):
            print(f"  {name}: {info['start_date']} → {info['end_date']} ({info['row_count']} rows)")
        print()


def main():
    parser = argparse.ArgumentParser(description="Master Sensei Data Updater")
    parser.add_argument("--macro-only", action="store_true")
    parser.add_argument("--daily-only", action="store_true")
    parser.add_argument("--intraday-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    cache = CacheManager(DATA_DIR)

    if args.status:
        show_status(cache)
        return

    run_all = not (args.macro_only or args.daily_only or args.intraday_only)

    if run_all or args.macro_only:
        logger.info("=== Updating macro data (FRED) ===")
        update_macro(cache)

    if run_all or args.daily_only:
        logger.info("=== Updating daily data (Tiingo) ===")
        update_daily(cache)

    if run_all or args.intraday_only:
        logger.info("=== Updating intraday data (Tiingo) ===")
        update_intraday(cache)

    show_status(cache)


if __name__ == "__main__":
    main()
