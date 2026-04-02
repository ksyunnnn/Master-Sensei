#!/usr/bin/env python3
"""Master Sensei Stop Hook — command型

stdinからhook入力JSONを受け取り、セッション終了前の確認事項をチェック。
- 確認事項なし → exit 0（出力なし）→ 停止許可
- 確認事項あり → exit 0 + {"decision":"block","reason":"..."} → 続行指示
- stop_hook_active=true → exit 0（無限ループ防止）
副作用なし（読み取りのみ）。
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from src.db import today_jst

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
    if last_updated < today_jst():
        return f"condition.mdの最終更新日が{last_updated}（今日は{today_jst()}）"
    return None


def check_unresolved_predictions() -> str | None:
    """期限切れの未解決予測をチェック"""
    if not DB_PATH.exists():
        return None

    import duckdb

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    overdue = conn.execute(
        "SELECT COUNT(*) FROM predictions WHERE outcome IS NULL AND deadline <= ?",
        [today_jst()],
    ).fetchone()[0]
    conn.close()

    if overdue > 0:
        return f"期限切れの未解決予測が{overdue}件あります"
    return None


def main():
    # stdinからhook入力を読み取り
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    # 無限ループ防止
    if hook_input.get("stop_hook_active"):
        sys.exit(0)

    # 確認事項チェック
    issues = []

    result = check_condition_md()
    if result:
        issues.append(result)

    result = check_unresolved_predictions()
    if result:
        issues.append(result)

    if issues:
        output = {
            "decision": "block",
            "reason": "セッション終了前に以下を確認してください:\n"
            + "\n".join(f"- {issue}" for issue in issues),
        }
        print(json.dumps(output, ensure_ascii=False))

    # issues なし → 出力なしで exit 0 → 停止許可


if __name__ == "__main__":
    main()
