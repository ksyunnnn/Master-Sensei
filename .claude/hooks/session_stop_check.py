#!/usr/bin/env python3
"""Master Sensei Stop Hook — 状態チェックスクリプト

prompt型Stopフックから呼び出され、セッション終了前の確認事項をstdoutに出力する。
副作用なし（読み取りのみ）。
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONDITION_MD = PROJECT_ROOT / "docs" / "condition.md"
DB_PATH = PROJECT_ROOT / "data" / "sensei.duckdb"


def check_condition_md() -> str | None:
    """condition.mdの最終更新日が今日かチェック"""
    if not CONDITION_MD.exists():
        return "condition.mdが存在しません"

    text = CONDITION_MD.read_text()
    match = re.search(r"Last updated:\s*(\d{4}-\d{2}-\d{2})", text)
    if not match:
        return "condition.mdにLast updatedが見つかりません"

    last_updated = date.fromisoformat(match.group(1))
    if last_updated < date.today():
        return f"condition.mdの最終更新日が{last_updated}（今日は{date.today()}）"
    return None


def check_unresolved_predictions() -> str | None:
    """期限切れの未解決予測をチェック"""
    if not DB_PATH.exists():
        return None

    import duckdb

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    overdue = conn.execute(
        "SELECT COUNT(*) FROM predictions WHERE outcome IS NULL AND deadline <= ?",
        [date.today()],
    ).fetchone()[0]
    conn.close()

    if overdue > 0:
        return f"期限切れの未解決予測が{overdue}件あります"
    return None


def main():
    issues = []

    result = check_condition_md()
    if result:
        issues.append(result)

    result = check_unresolved_predictions()
    if result:
        issues.append(result)

    if issues:
        print("セッション終了前の確認事項:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("確認事項なし")


if __name__ == "__main__":
    main()
