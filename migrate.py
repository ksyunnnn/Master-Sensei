"""データ移行スクリプト

移行元:
  - feasibility_study/macro/macro.duckdb → sensei.duckdb (events, event_reviews, regime_assessments)
  - feasibility_study/macro/macro.duckdb market_data → data/parquet/macro/ (シリーズ別Parquet)
  - backtest/data/cache/daily/*.parquet → data/parquet/daily/
  - backtest/data/cache/intraday/*.parquet → data/parquet/intraday/

変換:
  - market_data (行形式: date, series, value) → シリーズ別Parquet (date, value)
  - regime_assessments: 新カラム(vix_term_structure等)はNULLで移行
  - Parquetファイル: そのままコピー（メタデータ再生成）

Usage:
    python migrate.py                 # ドライラン（確認のみ）
    python migrate.py --execute       # 実行
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

# パス定義
MASTER_DIR = Path(__file__).parent
MACRO_DB_PATH = MASTER_DIR.parent / "feasibility_study" / "macro" / "macro.duckdb"
BACKTEST_CACHE = MASTER_DIR.parent / "backtest" / "data" / "cache"
SENSEI_DB_PATH = MASTER_DIR / "data" / "sensei.duckdb"
PARQUET_DIR = MASTER_DIR / "data" / "parquet"

# macro.duckdb の series名 → master_sensei の series名 マッピング
SERIES_MAPPING = {
    "VIX": "VIX",
    "BRENT": "BRENT",
    "US10Y": "US10Y",
    "FEDFUNDS": "FEDFUNDS",
}


def check_sources():
    """移行元の存在確認"""
    issues = []
    if not MACRO_DB_PATH.exists():
        issues.append(f"macro.duckdb not found: {MACRO_DB_PATH}")
    if not BACKTEST_CACHE.exists():
        issues.append(f"backtest cache not found: {BACKTEST_CACHE}")
    return issues


def preview():
    """移行内容のプレビュー"""
    print("=== Migration Preview ===\n")

    # macro.duckdb
    if MACRO_DB_PATH.exists():
        conn = duckdb.connect(str(MACRO_DB_PATH), read_only=True)
        for table in ["events", "event_reviews", "regime_assessments", "market_data"]:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  macro.duckdb/{table}: {count} rows")
        # market_data のシリーズ内訳
        series = conn.execute("SELECT series, COUNT(*) FROM market_data GROUP BY series ORDER BY series").fetchall()
        for s, c in series:
            target = SERIES_MAPPING.get(s, s)
            print(f"    {s} → parquet/macro/{target}.parquet ({c} rows)")
        conn.close()
    print()

    # backtest parquet
    daily_files = sorted((BACKTEST_CACHE / "daily").glob("*.parquet")) if (BACKTEST_CACHE / "daily").exists() else []
    intraday_files = sorted((BACKTEST_CACHE / "intraday").glob("*.parquet")) if (BACKTEST_CACHE / "intraday").exists() else []
    print(f"  backtest/daily: {len(daily_files)} files → parquet/daily/")
    for f in daily_files:
        print(f"    {f.name}")
    print(f"  backtest/intraday: {len(intraday_files)} files → parquet/intraday/")
    for f in intraday_files:
        print(f"    {f.name}")
    print()

    # 出力先
    print(f"  → sensei.duckdb: {SENSEI_DB_PATH}")
    print(f"  → parquet dir:   {PARQUET_DIR}")
    if SENSEI_DB_PATH.exists():
        print("  ⚠ sensei.duckdb already exists — will be overwritten")
    print()


def migrate_duckdb_tables():
    """macro.duckdb → sensei.duckdb へテーブル移行"""
    from src.db import SenseiDB

    # 既存のsensei.duckdbがあれば削除して新規作成
    if SENSEI_DB_PATH.exists():
        SENSEI_DB_PATH.unlink()
    wal = SENSEI_DB_PATH.with_suffix(".duckdb.wal")
    if wal.exists():
        wal.unlink()

    SENSEI_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 移行先を初期化
    dest_conn = duckdb.connect(str(SENSEI_DB_PATH))
    sensei = SenseiDB(dest_conn)

    # 移行元を開く
    src_conn = duckdb.connect(str(MACRO_DB_PATH), read_only=True)

    # events: スキーマ一致なので直接INSERT
    events = src_conn.execute("SELECT * FROM events ORDER BY id").fetchdf()
    if not events.empty:
        dest_conn.execute("DELETE FROM events")
        dest_conn.execute("INSERT INTO events SELECT * FROM events_df", {"events_df": events})
        # sequenceを最大IDに合わせる
        max_id = events["id"].max()
        dest_conn.execute(f"DROP SEQUENCE IF EXISTS events_id_seq")
        dest_conn.execute(f"CREATE SEQUENCE events_id_seq START {max_id + 1}")
    print(f"  events: {len(events)} rows migrated")

    # event_reviews: スキーマ一致
    reviews = src_conn.execute("SELECT * FROM event_reviews ORDER BY event_id, review_date").fetchdf()
    if not reviews.empty:
        dest_conn.execute("INSERT INTO event_reviews SELECT * FROM reviews_df", {"reviews_df": reviews})
    print(f"  event_reviews: {len(reviews)} rows migrated")

    # regime_assessments: 新カラム追加分はNULL
    regimes = src_conn.execute("SELECT * FROM regime_assessments ORDER BY date").fetchdf()
    for _, row in regimes.iterrows():
        sensei.save_regime(
            row["date"],
            vix_regime=row.get("vix_regime"),
            oil_regime=row.get("oil_regime"),
            overall=row.get("overall"),
            reasoning=row.get("reasoning"),
            # 旧スキーマにないカラムはNone（新規追加分）
            vix_term_structure=None,
            credit_regime=None,
            yield_curve_regime=row.get("rate_regime"),  # rate_regime → yield_curve_regime にマッピング
            dollar_regime=None,
        )
    print(f"  regime_assessments: {len(regimes)} rows migrated (rate_regime → yield_curve_regime)")

    src_conn.close()
    dest_conn.close()


def migrate_market_data_to_parquet():
    """macro.duckdb/market_data → シリーズ別Parquetファイル"""
    from src.cache_manager import CacheManager

    src_conn = duckdb.connect(str(MACRO_DB_PATH), read_only=True)
    cache = CacheManager(PARQUET_DIR)

    series_list = src_conn.execute("SELECT DISTINCT series FROM market_data ORDER BY series").fetchall()
    for (series_name,) in series_list:
        target_name = SERIES_MAPPING.get(series_name, series_name)
        rows = src_conn.execute(
            "SELECT date, value FROM market_data WHERE series = ? ORDER BY date",
            [series_name],
        ).fetchdf()
        if rows.empty:
            continue
        rows["date"] = pd.to_datetime(rows["date"])
        rows = rows.set_index("date")
        cache.save_macro(target_name, rows)
        print(f"  market_data/{series_name} → macro/{target_name}.parquet ({len(rows)} rows)")

    src_conn.close()


def migrate_price_parquet():
    """backtest/cache/ → data/parquet/ へParquetファイルをコピー"""
    from src.cache_manager import CacheManager

    cache = CacheManager(PARQUET_DIR)

    # daily
    daily_src = BACKTEST_CACHE / "daily"
    if daily_src.exists():
        for f in sorted(daily_src.glob("*.parquet")):
            dest = PARQUET_DIR / "daily" / f.name
            shutil.copy2(f, dest)
            # メタデータ再生成のためにload→save
            df = pd.read_parquet(dest)
            symbol = f.stem
            cache.save_daily(symbol, df)
            print(f"  daily/{f.name} → ({len(df)} rows)")

    # intraday
    intraday_src = BACKTEST_CACHE / "intraday"
    if intraday_src.exists():
        for f in sorted(intraday_src.glob("*.parquet")):
            dest = PARQUET_DIR / "intraday" / f.name
            shutil.copy2(f, dest)
            df = pd.read_parquet(dest)
            symbol = f.stem.replace("_5min", "")
            cache.save_intraday(symbol, df)
            print(f"  intraday/{f.name} → ({len(df)} rows)")


def main():
    parser = argparse.ArgumentParser(description="Master Sensei Data Migration")
    parser.add_argument("--execute", action="store_true", help="Execute migration (default: dry run)")
    args = parser.parse_args()

    issues = check_sources()
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}")
        return

    preview()

    if not args.execute:
        print("Dry run complete. Use --execute to run migration.")
        return

    print("=== Executing Migration ===\n")

    print("[1/3] DuckDB tables (events, event_reviews, regime_assessments)")
    migrate_duckdb_tables()
    print()

    print("[2/3] Market data → Parquet")
    migrate_market_data_to_parquet()
    print()

    print("[3/3] Price data Parquet files")
    migrate_price_parquet()
    print()

    print("=== Migration Complete ===")


if __name__ == "__main__":
    main()
