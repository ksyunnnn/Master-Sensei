#!/usr/bin/env python3
"""Master Sensei SessionStart Hook

セッション開始時に実行され、stdoutがClaudeのコンテキストに注入される。
副作用なし（読み取りのみ）。SQLはSenseiDBに委譲（ADR-008）。
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db import today_jst, now_jst

DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "sensei.duckdb"
PARQUET_DIR = DATA_DIR / "parquet"


def to_date(val) -> date:
    """pandas Timestamp や datetime を date に変換"""
    if hasattr(val, "date"):
        return val.date()
    return val


def check_predictions(db) -> list[str]:
    """期限切れ・期限間近の予測を検出"""
    messages = []
    today = today_jst()

    counts = db.get_prediction_counts()
    if counts["total"] > 0:
        messages.append(f"  予測: {counts['total']}件 (解決済み{counts['resolved']}, 未解決{counts['pending']})")

    pending = db.get_pending_predictions()
    for row in pending:
        deadline = to_date(row["deadline"])
        subj = row["subject"]
        conf = row["confidence"]
        pred_id = row["id"]
        if deadline < today:
            messages.append(f"  [ACTION] 予測#{pred_id}が期限切れ（{subj}, 期限{deadline}, 確信度{conf:.0%}）→ resolve_predictionを実行せよ")
        elif deadline <= today + timedelta(days=1):
            messages.append(f"  [期限間近] 予測#{pred_id}: {subj} (期限{deadline}, 確信度{conf:.0%})")

    return messages


def check_regime(db) -> list[str]:
    """最新レジーム判定を表示"""
    regime = db.get_latest_regime()
    if not regime:
        return ["  レジーム: 未判定"]

    age = (today_jst() - to_date(regime["date"])).days
    freshness = "" if age == 0 else f" ({age}日前)"
    messages = [f"  レジーム: {regime['overall']}{freshness}"]
    if regime.get("reasoning"):
        messages.append(f"  根拠: {regime['reasoning'][:100]}")
    return messages


def check_knowledge(db) -> list[str]:
    """stale知見を検出"""
    active = db.get_active_knowledge()
    stale = db.get_stale_knowledge()

    messages = [f"  知見: {len(active)}件 (active)"]
    if stale:
        messages.append(f"  [警告] {len(stale)}件が180日以上未検証")
    return messages


def check_brier(db) -> list[str]:
    """Brier scoreの状態"""
    score = db.get_brier_score()
    if score is not None:
        return [f"  Brier score: {score:.3f}"]
    return []


def check_data_freshness() -> list[str]:
    """Parquetデータの鮮度を確認"""
    messages = []
    today = today_jst()

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


def main():
    now = now_jst()
    lines = [
        "[Master Sensei 状態チェック]",
        f"  現在: {now.strftime('%Y-%m-%d %H:%M JST')}",
        "",
    ]

    if DB_PATH.exists():
        import duckdb
        from src.db import SenseiDB

        conn = duckdb.connect(str(DB_PATH))
        db = SenseiDB(conn)

        lines.extend(check_predictions(db))
        lines.append("")
        lines.extend(check_regime(db))
        lines.append("")
        lines.extend(check_knowledge(db))
        lines.append("")
        lines.extend(check_brier(db))

        conn.close()
    else:
        lines.append("  sensei.duckdb: 未作成")

    lines.append("")
    lines.extend(check_data_freshness())

    print("\n".join(lines))


if __name__ == "__main__":
    main()
