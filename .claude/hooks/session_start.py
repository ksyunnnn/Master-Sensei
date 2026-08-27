#!/usr/bin/env python3
"""Master Sensei SessionStart Hook

セッション開始時に実行され、stdoutがClaudeのコンテキストに注入される。
読み取りのみ（例外: 前セッションの終了 sentinel が残っていれば掃除する）。
SQLはSenseiDBに委譲（ADR-008）。
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
# Stop hook の終了チェックを発火させる sentinel（session_stop_check.py と対）。
# 前セッションが異常終了して残っていた場合に備え、開始時に掃除する。
SENTINEL = PROJECT_ROOT / ".claude" / ".session_ending"


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


def check_market_calendar() -> list[str]:
    """米株(NYSE/Nasdaq)の当日ステータス。休場/早引け/週末のみ注意喚起（通常日は無音）。

    SoT は calendar/us_market_holidays.ics（NYSE公式由来・検証済、認証不要）。
    フックを壊さないため、範囲外(未更新)・読込失敗は握りつぶして空を返す。
    """
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "calendar"))
        import market_calendar as mc

        today = today_jst()
        if mc.market_status(today) == "open":
            return []  # 通常営業日はノイズを出さない
        return [f"  米株: {mc.describe(today)}"]
    except ValueError:
        # カバレッジ範囲外＝フィード未更新
        return ["  米株カレンダー: 当日がデータ範囲外 → calendar/generate_holidays_ics.py に年を追加して再生成を"]
    except Exception:
        return []  # 判定失敗でも状態チェック全体は落とさない


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


def check_position() -> list[str]:
    """建玉があれば監視の起動を [ACTION] で促す。

    セッションをまたぐ常駐監視は Claude Code に無い（Monitor も CronCreate も
    セッション寿命。issue #22 の公式仕様調査）。したがって「毎セッションで
    監視を立て直す」ことを人間の記憶に頼らず hook で強制する。

    建玉は執行事実層（parquet）から読む。Saxo API を叩かないので token 失効に
    影響されず、hook の 10秒 timeout にも収まる。価格は取りに行かない（同上）。
    """
    try:
        from scripts.watch_position import load_position
    except Exception as exc:
        return [f"  建玉: 判定不能（{type(exc).__name__}）"]

    try:
        pos = load_position("SOXL")
    except Exception as exc:
        return [f"  建玉: 判定不能（{type(exc).__name__}: {exc}）"]

    if pos is None or pos.quantity <= 0:
        return ["  建玉: なし"]

    return [
        f"  建玉: SOXL {pos.quantity:g}株 建値${pos.avg_price:.3f} 取得原価${pos.cost_usd:,.2f}",
        "  [ACTION] 建玉がある。`python scripts/watch_position.py` を run_in_background で"
        "起動し、水準アラート(--alert-above/--alert-below)を建値・目標に設定せよ。"
        "同時に Saxo token の有効性を確認し、失効していれば scripts/saxo_oauth_init.py を"
        "起動してユーザーにブラウザログインを促せ（発注経路が死んでいると判断しても執行できない）",
    ]


def main():
    # 前セッションの leftover 終了 sentinel を掃除（次の Stop で誤発火させない）
    try:
        SENTINEL.unlink()
    except FileNotFoundError:
        pass

    now = now_jst()
    lines = [
        "[Master Sensei 状態チェック]",
        f"  現在: {now.strftime('%Y-%m-%d %H:%M JST')}",
    ]
    market_lines = check_market_calendar()
    if market_lines:
        lines.extend(market_lines)
    lines.append("")

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
        lines.append("")
        lines.extend(check_position())

        conn.close()
    else:
        lines.append("  sensei.duckdb: 未作成")

    lines.append("")
    lines.extend(check_data_freshness())

    print("\n".join(lines))


if __name__ == "__main__":
    main()
