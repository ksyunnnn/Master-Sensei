#!/usr/bin/env python
"""sensei.duckdb 蓄積層の git バックアップ (ADR-033)。

蓄積層 (events/predictions/knowledge/regime_assessments/event_reviews/trades/
skill_executions) を CSV で `data/db_export/` に決定的に export する。
auth_tokens は機密のため除外 (public repo 漏洩防止)。内容不変なら git 差分は出ない。

使い方:
    python scripts/backup_db.py                 # backup (export)
    python scripts/backup_db.py --restore       # CSV から復元 (空 DB に対して)
    python scripts/backup_db.py --dir data/db_export --db data/sensei.duckdb

`python update_data.py` の末尾でも自動実行される (--no-backup で抑止)。
Stop フックには載せない (ADR-033)。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.db import SenseiDB  # noqa: E402

DEFAULT_DB = "data/sensei.duckdb"
DEFAULT_DIR = "data/db_export"


def backup(db_path: str = DEFAULT_DB, export_dir: str = DEFAULT_DIR) -> dict:
    """蓄積層を CSV へ export する (read-only 接続=安全)。"""
    conn = duckdb.connect(db_path, read_only=True)
    try:
        db = SenseiDB(conn, init_schema=False)
        result = db.export_for_backup(export_dir)
    finally:
        conn.close()
    total = sum(result["tables"].values())
    print(f"backup OK: {len(result['tables'])} tables / {total} rows -> {result['dir']}")
    return result


def restore(db_path: str, export_dir: str = DEFAULT_DIR) -> dict:
    """CSV から復元する。既存ファイルへの上書きは想定しない (空 DB を指定)。"""
    if Path(db_path).exists():
        raise SystemExit(
            f"復元先 {db_path} が既に存在します。空のパスを指定してください "
            f"(既存DB破壊防止)。"
        )
    conn = duckdb.connect(db_path)
    try:
        db = SenseiDB(conn)  # _init_schema でテーブル+sequence 作成
        result = db.restore_from_backup(export_dir)
    finally:
        conn.close()
    total = sum(result["tables"].values())
    print(f"restore OK: {total} rows -> {db_path}")
    return result


def main():
    parser = argparse.ArgumentParser(description="sensei.duckdb git backup (ADR-033)")
    parser.add_argument("--restore", action="store_true", help="CSV から復元する")
    parser.add_argument("--db", default=DEFAULT_DB, help="DuckDB パス")
    parser.add_argument("--dir", default=DEFAULT_DIR, help="export ディレクトリ")
    args = parser.parse_args()
    if args.restore:
        restore(args.db, args.dir)
    else:
        backup(args.db, args.dir)


if __name__ == "__main__":
    main()
