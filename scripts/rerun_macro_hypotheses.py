"""requires_macro仮説を5年マクロデータで再実行する

signal_ideas.csvの該当行を置き換える。既存の非マクロ結果は維持。

使い方:
    python scripts/rerun_macro_hypotheses.py --dry-run
    python scripts/rerun_macro_hypotheses.py
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.signal_defs import HYPOTHESES  # noqa: E402
from src.signal_runner import run_all  # noqa: E402

MAIN_CSV = ROOT / "data" / "research" / "signal_ideas.csv"
TEMP_CSV = ROOT / "data" / "research" / "signal_ideas_macro_rerun.csv"
BACKUP_CSV = ROOT / "data" / "research" / "signal_ideas.csv.bak"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--shuffle-perms", type=int, default=1000)
    parser.add_argument("--random-sims", type=int, default=1000)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger(__name__)

    # マクロ仮説抽出
    macro_hyps = [h for h in HYPOTHESES if h.get("requires_macro")]
    macro_ids = {h["id"] for h in macro_hyps}
    logger.info("マクロ仮説: %d件, 対象ID数: %d", len(macro_hyps), len(macro_ids))

    if args.dry_run:
        print(f"Dry-run: {len(macro_hyps)}仮説を再実行予定")
        print(f"  削除予定行: signal_ideas.csv の {len(macro_ids)}ID分")
        return 0

    # メインCSVをバックアップ
    if MAIN_CSV.exists():
        import shutil
        shutil.copy2(MAIN_CSV, BACKUP_CSV)
        logger.info("バックアップ作成: %s", BACKUP_CSV)

    # 一時CSVを削除（前回実行の残骸クリア）
    if TEMP_CSV.exists():
        TEMP_CSV.unlink()

    # 再実行（一時CSVに書き込み）
    logger.info("マクロ仮説の再実行開始")
    results = run_all(
        hypotheses=macro_hyps,
        output_path=TEMP_CSV,
        shuffle_n_perms=args.shuffle_perms,
        random_n_sims=args.random_sims,
    )
    logger.info("再実行完了: %d件", len(results))

    # メインCSVから該当IDを除去し、新結果を追加
    main_df = pd.read_csv(MAIN_CSV)
    new_df = pd.read_csv(TEMP_CSV)

    before_n = len(main_df)
    main_df = main_df[~main_df["id"].isin(macro_ids)]
    after_removal = len(main_df)
    logger.info("既存行削除: %d → %d (%d行削除)", before_new := before_n, after_removal, before_n - after_removal)

    # カラム整合性チェック
    main_cols = set(main_df.columns)
    new_cols = set(new_df.columns)
    if main_cols != new_cols:
        logger.warning("カラム不一致: main-new=%s, new-main=%s",
                       main_cols - new_cols, new_cols - main_cols)

    merged = pd.concat([main_df, new_df], ignore_index=True, sort=False)
    logger.info("結合後: %d行", len(merged))

    # passed_v2を再計算
    from src.signal_runner import REFUTATION_JUDGE_MAP

    def judge(row):
        if row["n_samples"] < 30 or pd.isna(row.get("metric_value")):
            return False
        screen_pass = False
        if row["metric_name"] == "direction_agreement":
            screen_pass = row["metric_value"] > 0.5
        elif row["metric_name"] == "spearman_r":
            screen_pass = (row["metric_value"] > 0 if row["direction"] == "long"
                           else row["metric_value"] < 0)
        if not screen_pass:
            return False
        bt = row["bias_test_type"]
        judge_tests = list(REFUTATION_JUDGE_MAP[bt])
        if row.get("signal_dtype") == "float":
            judge_tests = [t for t in judge_tests
                           if t not in ("random_data", "reverse_direction")]
        col_map = {
            "shuffle": "refute_shuffle_passed",
            "random_data": "refute_random_data_passed",
            "reverse_direction": "refute_reverse_direction_passed",
            "period_exclusion": "refute_period_exclusion_passed",
        }
        for t in judge_tests:
            v = row.get(col_map[t])
            if pd.isna(v):
                continue
            if str(v).lower() not in ("true", "1", "1.0"):
                return False
        return True

    merged["passed_v2"] = merged.apply(judge, axis=1)

    merged.to_csv(MAIN_CSV, index=False)
    logger.info("signal_ideas.csv 更新完了: 通過v2=%d/%d", merged["passed_v2"].sum(), len(merged))

    # 一時CSV削除
    TEMP_CSV.unlink()

    return 0


if __name__ == "__main__":
    sys.exit(main())
