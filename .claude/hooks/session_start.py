#!/usr/bin/env python3
"""Master Sensei SessionStart Hook

セッション開始時に実行され、stdoutがClaudeのコンテキストに注入される。
副作用なし（読み取りのみ）。
"""
import sys
from datetime import date, timedelta
from pathlib import Path

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "sensei.duckdb"
PARQUET_DIR = DATA_DIR / "parquet"


def check_predictions(conn) -> list[str]:
    """期限切れ・期限間近の予測を検出"""
    messages = []
    today = date.today()

    # 期限切れ（未解決）
    overdue = conn.execute(
        "SELECT id, subject, deadline, confidence FROM predictions "
        "WHERE outcome IS NULL AND deadline < ?",
        [today],
    ).fetchall()
    for row in overdue:
        messages.append(f"  [期限切れ] 予測#{row[0]}: {row[1]} (期限{row[2]}, 確信度{row[3]:.0%}) → 解決が必要")

    # 期限が今日または明日
    upcoming = conn.execute(
        "SELECT id, subject, deadline, confidence FROM predictions "
        "WHERE outcome IS NULL AND deadline >= ? AND deadline <= ?",
        [today, today + timedelta(days=1)],
    ).fetchall()
    for row in upcoming:
        messages.append(f"  [期限間近] 予測#{row[0]}: {row[1]} (期限{row[2]}, 確信度{row[3]:.0%})")

    # 統計
    total = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    resolved = conn.execute("SELECT COUNT(*) FROM predictions WHERE outcome IS NOT NULL").fetchone()[0]
    if total > 0:
        messages.insert(0, f"  予測: {total}件 (解決済み{resolved}, 未解決{total - resolved})")

    return messages


def check_regime(conn) -> list[str]:
    """最新レジーム判定を表示"""
    messages = []
    row = conn.execute(
        "SELECT date, overall, reasoning FROM regime_assessments ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if row:
        age = (date.today() - row[0]).days
        freshness = "" if age == 0 else f" ({age}日前)"
        messages.append(f"  レジーム: {row[1]}{freshness}")
        if row[2]:
            messages.append(f"  根拠: {row[2][:100]}")
    else:
        messages.append("  レジーム: 未判定")
    return messages


def check_knowledge(conn) -> list[str]:
    """stale知見を検出"""
    messages = []
    total = conn.execute("SELECT COUNT(*) FROM knowledge WHERE verification_status != 'invalidated'").fetchone()[0]
    stale = conn.execute(
        "SELECT COUNT(*) FROM knowledge "
        "WHERE verification_status NOT IN ('invalidated') "
        "AND (last_verified_date IS NULL OR last_verified_date < current_date - INTERVAL '180 days')"
    ).fetchone()[0]

    messages.append(f"  知見: {total}件 (active)")
    if stale > 0:
        messages.append(f"  [警告] {stale}件が180日以上未検証")
    return messages


def check_data_freshness() -> list[str]:
    """Parquetデータの鮮度を確認"""
    import json

    messages = []
    today = date.today()

    for meta_file, label in [
        (PARQUET_DIR / "metadata.json", "日足"),
        (PARQUET_DIR / "metadata_intraday.json", "5分足"),
        (PARQUET_DIR / "metadata_macro.json", "マクロ"),
    ]:
        if not meta_file.exists():
            messages.append(f"  {label}: データなし")
            continue
        with open(meta_file) as f:
            meta = json.load(f)
        if not meta:
            messages.append(f"  {label}: データなし")
            continue
        latest_date = max(v["end_date"] for v in meta.values())
        age = (today - date.fromisoformat(latest_date)).days
        count = len(meta)
        if age > 1:
            messages.append(f"  {label}: {count}シンボル, 最新{latest_date} ({age}日前) → 更新推奨")
        else:
            messages.append(f"  {label}: {count}シンボル, 最新{latest_date}")

    return messages


def check_brier(conn) -> list[str]:
    """Brier scoreの状態"""
    messages = []
    row = conn.execute("SELECT AVG(brier_score) FROM predictions WHERE brier_score IS NOT NULL").fetchone()
    if row[0] is not None:
        messages.append(f"  Brier score: {row[0]:.3f}")
    return messages


def main():
    lines = ["[Master Sensei 状態チェック]", ""]

    # DB確認
    if DB_PATH.exists():
        import duckdb
        conn = duckdb.connect(str(DB_PATH), read_only=True)

        lines.extend(check_predictions(conn))
        lines.append("")
        lines.extend(check_regime(conn))
        lines.append("")
        lines.extend(check_knowledge(conn))
        lines.append("")
        lines.extend(check_brier(conn))

        conn.close()
    else:
        lines.append("  sensei.duckdb: 未作成")

    lines.append("")
    lines.extend(check_data_freshness())

    print("\n".join(lines))


if __name__ == "__main__":
    main()
