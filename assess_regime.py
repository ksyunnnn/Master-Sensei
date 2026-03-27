"""レジーム判定実行スクリプト

Parquetの最新マクロデータからレジーム判定を行い、sensei.duckdbに記録する。

Usage:
    python assess_regime.py              # 判定して記録
    python assess_regime.py --dry-run    # 判定のみ（記録しない）
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from src.cache_manager import CacheManager
from src.db import SenseiDB
from src.regime import assess_regime

DATA_DIR = Path(__file__).parent / "data"
PARQUET_DIR = DATA_DIR / "parquet"
DB_PATH = DATA_DIR / "sensei.duckdb"


SERIES_NAMES = ["VIX", "VIX3M", "HY_SPREAD", "YIELD_CURVE", "BRENT", "USD_INDEX"]


def load_latest_macro(cache: CacheManager, db: SenseiDB = None) -> dict:
    """各マクロ指標の最新値を取得

    ADR-005: market_observations → Parquetの優先順位で最新値を解決。
    各シリーズについて、より新しい日付のデータを採用する。
    """
    # Parquetから取得
    parquet_values = {}
    parquet_dates = {}
    for series in SERIES_NAMES:
        df = cache.load_macro(series)
        if not df.empty:
            parquet_values[series] = df["value"].iloc[-1]
            parquet_dates[series] = df.index[-1].date() if hasattr(df.index[-1], 'date') else df.index[-1]

    # market_observationsから取得（あれば上書き）
    obs_values = {}
    obs_dates = {}
    obs_sources = {}
    if db:
        obs = db.get_latest_observations()
        for row in obs:
            s = row["series"]
            if s in SERIES_NAMES:
                obs_values[s] = row["value"]
                obs_dates[s] = row["date"]
                obs_sources[s] = row["source"]

    # マージ: より新しい日付のデータを採用
    values = {}
    for series in SERIES_NAMES:
        p_date = parquet_dates.get(series)
        o_date = obs_dates.get(series)

        if p_date and o_date:
            if o_date >= p_date:
                values[series] = obs_values[series]
                print(f"  {series}: {obs_values[series]} (obs {o_date}, source={obs_sources[series]})")
            else:
                values[series] = parquet_values[series]
        elif o_date:
            values[series] = obs_values[series]
            print(f"  {series}: {obs_values[series]} (obs {o_date}, source={obs_sources[series]})")
        elif p_date:
            values[series] = parquet_values[series]

    return values


def run(dry_run: bool = False):
    cache = CacheManager(PARQUET_DIR)

    # sensei.duckdbが存在すればmarket_observationsも参照
    db = None
    if DB_PATH.exists():
        conn = duckdb.connect(str(DB_PATH))
        db = SenseiDB(conn)
    latest = load_latest_macro(cache, db)

    if not latest:
        print("マクロデータなし。先に python update_data.py --macro-only を実行してください。")
        return

    result = assess_regime(
        vix=latest.get("VIX"),
        vix3m=latest.get("VIX3M"),
        hy_spread=latest.get("HY_SPREAD"),
        yield_curve=latest.get("YIELD_CURVE"),
        oil=latest.get("BRENT"),
        usd=latest.get("USD_INDEX"),
    )

    print(f"Overall: {result.overall} (score: {result.overall_score})")
    print()
    for ind in result.indicators:
        print(f"  {ind.name}: {ind.regime} (score={ind.score}) — {ind.note}")
    print()

    if dry_run:
        print("(dry-run: DBへの記録をスキップ)")
        if db:
            conn.close()
        return

    # sensei.duckdbに記録
    if not db:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(DB_PATH))
        db = SenseiDB(conn)

    # 既存の同日レジームがあるか確認
    existing = db.get_latest_regime()
    today = date.today()

    if existing and existing["date"] == today and existing["overall"] == result.overall:
        print(f"本日({today})の判定は既に記録済み（{result.overall}）。変化なしのためスキップ。")
        conn.close()
        return

    # 指標別regimeを取得
    ind_map = {ind.name: ind.regime for ind in result.indicators}

    db.save_regime(
        today,
        vix_regime=ind_map.get("VIX"),
        vix_term_structure=ind_map.get("VIX_TERM"),
        credit_regime=ind_map.get("HY_SPREAD"),
        yield_curve_regime=ind_map.get("YIELD_CURVE"),
        oil_regime=ind_map.get("OIL"),
        dollar_regime=ind_map.get("USD"),
        overall=result.overall,
        reasoning=result.reasoning,
    )
    print(f"→ sensei.duckdb に記録しました ({today}: {result.overall})")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Master Sensei Regime Assessment")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
