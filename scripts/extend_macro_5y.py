"""FRED 9系列を5年分に拡張するスクリプト

既存parquetを.bak2に退避し、5年分の履歴データで上書きする。
metadata_macro.jsonも合わせて更新する。

使い方:
    cd master_sensei_1000_idea
    python scripts/extend_macro_5y.py --dry-run  # 実行せず取得内容を確認
    python scripts/extend_macro_5y.py            # 本実行
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".." / "master_sensei"))
from src.fred_client import FredClient, SERIES_CONFIG  # type: ignore  # noqa: E402

MASTER_SENSEI_DIR = Path(__file__).resolve().parent.parent / ".." / "master_sensei"
MACRO_DIR = MASTER_SENSEI_DIR / "data" / "parquet" / "macro"
METADATA_PATH = MASTER_SENSEI_DIR / "data" / "parquet" / "metadata_macro.json"

YEARS = 5
JST = timezone(timedelta(hours=9))


def load_env_fred_key() -> str:
    env_path = MASTER_SENSEI_DIR / ".env"
    if not env_path.exists():
        raise FileNotFoundError(f".env not found: {env_path}")
    for line in env_path.read_text().splitlines():
        if line.startswith("FRED_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise ValueError("FRED_API_KEY not found in .env")


def backup_current(series_name: str) -> None:
    src = MACRO_DIR / f"{series_name}.parquet"
    dst = MACRO_DIR / f"{series_name}.parquet.bak2"
    if src.exists():
        shutil.copy2(src, dst)


def fetch_and_save(client: FredClient, series_name: str, fred_id: str,
                   start: date, end: date, dry_run: bool) -> dict:
    """1系列を取得してparquetに保存。メタデータ情報を返す。"""
    records = client.fetch_series(fred_id, start_date=start, end_date=end)
    if not records:
        raise RuntimeError(f"{series_name}: no records returned")

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df["source"] = "fred"
    df["updated_at"] = pd.Timestamp(datetime.now(JST))

    n = len(df)
    start_d = df.index.min().date().isoformat()
    end_d = df.index.max().date().isoformat()

    if not dry_run:
        out_path = MACRO_DIR / f"{series_name}.parquet"
        df.to_parquet(out_path)

    return {
        "symbol": series_name,
        "start_date": start_d,
        "end_date": end_d,
        "last_updated": datetime.now(JST).isoformat(),
        "row_count": n,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="実行せず取得内容を表示")
    args = parser.parse_args()

    api_key = load_env_fred_key()
    client = FredClient(api_key=api_key)

    today = date.today()
    start = today - timedelta(days=365 * YEARS)
    print(f"FRED 5年取得: {start} → {today}")
    print(f"保存先: {MACRO_DIR}")
    print(f"Dry-run: {args.dry_run}")
    print()

    new_meta: dict = {}
    for series_name, fred_id in SERIES_CONFIG.items():
        print(f"  {series_name:12s} ({fred_id}) ... ", end="", flush=True)
        if not args.dry_run:
            backup_current(series_name)
        try:
            meta = fetch_and_save(client, series_name, fred_id, start, today, args.dry_run)
            new_meta[series_name] = meta
            print(f"N={meta['row_count']:5d}, {meta['start_date']} → {meta['end_date']}")
        except Exception as e:
            print(f"FAILED: {e}")
            return 1

    if args.dry_run:
        print("\n[DRY-RUN] parquet / metadata_macro.json は更新していません")
        return 0

    # metadata_macro.json を更新（全系列を一括上書き）
    METADATA_PATH.write_text(json.dumps(new_meta, indent=2, ensure_ascii=False))
    print(f"\nmetadata_macro.json 更新済み")

    # 検証
    print("\n=== 検証 ===")
    for series_name in SERIES_CONFIG:
        df = pd.read_parquet(MACRO_DIR / f"{series_name}.parquet")
        print(f"  {series_name:12s}: {len(df):5d}行, "
              f"{df.index.min().date()} → {df.index.max().date()}, "
              f"NaN={df['value'].isna().sum()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
