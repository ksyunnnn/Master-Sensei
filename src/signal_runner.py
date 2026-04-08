"""シグナルランナー（ADR-021: Round 1 機械実行）

HYPOTHESESを順次読み、screen_signal + 反証テストを機械実行する。
Agent裁量なし。判断ロジックゼロ。

使い方:
    python -m src.signal_runner              # 全仮説×全シンボル
    python -m src.signal_runner --dry-run    # 実行せず仮説数を表示
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src.research_utils import (
    RefutationResult,
    SignalTestResult,
    load_daily,
    load_polygon_5min,
    period_exclusion_test,
    random_data_control,
    record_result,
    reverse_direction_test,
    screen_signal,
    shuffle_test,
)
from src.signal_defs import HYPOTHESES

logger = logging.getLogger(__name__)

# ── 定数 ──

# 日足シンボル（master_sensei/data/parquet/daily/に存在する10銘柄）
SYMBOLS_DAILY: list[str] = [
    "SOXL", "SOXS", "TQQQ", "SQQQ", "TECL",
    "TECS", "TNA", "TZA", "SPXL", "VIXY",
]

# Polygon 5分足シンボル（18銘柄）
SYMBOLS_INTRADAY: list[str] = [
    "SOXL", "SOXS", "TQQQ", "SQQQ", "TECL", "TECS",
    "SPXL", "TNA", "TZA", "VIXY",
    "SOXX", "SPY", "QQQ", "HYG", "TLT", "USO", "UUP", "IWM",
]

# Bull → Bear ペアマッピング（Cat 23,26,29,30,34,64等）
BEAR_PAIR_MAP: dict[str, str] = {
    "SOXL": "SOXS",
    "TQQQ": "SQQQ",
    "TECL": "TECS",
    "SPXL": "SH",   # SPXLのBearはSH（3xはSPXSだがPolygonになし → 日足で代替検討）
    "TNA": "TZA",
}

# Cat 8 のペア: 全シンボルに対してVIXYをペアとして使用
VIXY_PAIR_CATEGORIES: set[int] = {8}

# Cat 11 のクロスセクターペア
CROSS_SECTOR_PAIR_MAP: dict[str, str] = {
    "SOXL": "TQQQ",
    "TQQQ": "SOXL",
    "TECL": "TQQQ",
    "SPXL": "TQQQ",
    "TNA": "TQQQ",
}

# データディレクトリ
DEFAULT_DAILY_DIR = Path(__file__).resolve().parent.parent / ".." / "master_sensei" / "data" / "parquet" / "daily"
DEFAULT_INTRADAY_DIR = Path(__file__).resolve().parent.parent / ".." / "master_sensei" / "data" / "research" / "polygon_intraday"
DEFAULT_MACRO_DIR = Path(__file__).resolve().parent.parent / ".." / "master_sensei" / "data" / "parquet" / "macro"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "research" / "executions_new.csv"

# ADR-013 L136-146: bias_test_typeごとの反証テスト判定マッピング
# 全テストを全仮説に対して「実行」するが、「判定に使う」のはこのマッピングに従う
#
# random_data_controlはStage 1判定から除外（選択肢1、2026-04-05決定）:
#   screen_signalの通過基準（方向一致率>50%）が意図的に緩い（Stage 1偽陰性回避）ため、
#   ランダムリターンに対してFP率≈50%となり閾値10%を常に超える。Stage 1の設計思想と矛盾する。
#   実行・記録は継続し、Stage 2でp値ベースの判定に使う。
REFUTATION_JUDGE_MAP: dict[str, list[str]] = {
    "unconditional": ["shuffle", "reverse_direction", "period_exclusion"],
    "regime_conditional": ["shuffle", "reverse_direction"],
    "structural": ["shuffle", "reverse_direction", "period_exclusion"],
    "direction_fixed": ["shuffle", "period_exclusion"],
}


# ── データ準備 ──


def merge_macro(
    df: pd.DataFrame,
    macro_names: list[str],
    macro_dir: Path | str = DEFAULT_MACRO_DIR,
) -> pd.DataFrame:
    """マクロParquetを読み込み、日付ベースでdfに列マージする。

    Args:
        df: 日足 or 5分足DataFrame
        macro_names: マクロ系列名のリスト (例: ["VIX", "VIX3M"])
        macro_dir: マクロParquetディレクトリ

    Returns:
        マクロ列が追加されたDataFrame
    """
    if not macro_names:
        return df

    result = df.copy()
    macro_dir = Path(macro_dir)

    for name in macro_names:
        col_name = name.lower()
        path = macro_dir / f"{name}.parquet"
        if not path.exists():
            logger.warning("マクロファイルが見つかりません: %s", path)
            result[col_name] = np.nan
            continue

        macro_df = pd.read_parquet(path)
        # macro_dfのindex→date, value列をマッピング
        value_col = macro_df.columns[0] if len(macro_df.columns) == 1 else "value"
        if value_col not in macro_df.columns:
            value_col = macro_df.columns[0]

        date_to_value = {}
        for idx, row in macro_df.iterrows():
            d = idx.date() if hasattr(idx, "date") else idx
            date_to_value[d] = row[value_col]

        # dfのindexからdateを抽出してマッピング
        bar_dates = [ts.date() if hasattr(ts, "date") else ts for ts in result.index]
        result[col_name] = [date_to_value.get(d, np.nan) for d in bar_dates]

    return result


def merge_pair(
    df: pd.DataFrame,
    pair_symbol: str,
    daily_dir: Path | str = DEFAULT_DAILY_DIR,
    intraday_dir: Path | str = DEFAULT_INTRADAY_DIR,
    timeframe: str = "daily",
) -> pd.DataFrame:
    """ペアシンボルのClose/Volumeをdfにマージする。

    Args:
        df: 主シンボルのDataFrame
        pair_symbol: ペアシンボル名
        daily_dir: 日足ディレクトリ
        intraday_dir: 5分足ディレクトリ
        timeframe: "daily" or "intraday"

    Returns:
        pair_Close, pair_Volume列が追加されたDataFrame
    """
    result = df.copy()

    try:
        if timeframe == "intraday":
            pair_df = load_polygon_5min(pair_symbol, data_dir=intraday_dir, daily_dir=daily_dir)
        else:
            pair_df = load_daily(pair_symbol, data_dir=daily_dir)
    except FileNotFoundError:
        logger.warning("ペアシンボル '%s' のデータが見つかりません", pair_symbol)
        result["pair_Close"] = np.nan
        result["pair_Volume"] = np.nan
        return result

    # indexでalign（主シンボル側のindexを維持）
    result["pair_Close"] = pair_df["Close"].reindex(result.index)
    result["pair_Volume"] = pair_df["Volume"].reindex(result.index)

    return result


def resolve_pair_symbol(symbol: str, category: int) -> str | None:
    """仮説のカテゴリとシンボルからペアシンボルを決定する。

    Returns:
        ペアシンボル名。ペアが不要またはマッピングがない場合はNone。
    """
    if category in VIXY_PAIR_CATEGORIES:
        return "VIXY" if symbol != "VIXY" else None
    if category == 11:
        return CROSS_SECTOR_PAIR_MAP.get(symbol)
    # デフォルト: Bear対応
    return BEAR_PAIR_MAP.get(symbol)


# ── リターン計算 ──


def compute_next_returns(df: pd.DataFrame, timeframe: str) -> pd.Series:
    """次バーリターンを計算する。

    signal[T] を評価するための returns[T] = (Close[T+1] - Close[T]) / Close[T]。

    Args:
        df: OHLCV DataFrame
        timeframe: "daily", "daily_macro", or "intraday"

    Returns:
        次バーリターンのSeries（最終バーはNaN）
    """
    return df["Close"].pct_change().shift(-1)


# ── 仮説実行 ──


def run_hypothesis(
    hyp: dict,
    df: pd.DataFrame,
    symbol: str,
    shuffle_seed: int = 42,
    shuffle_n_perms: int = 1000,
    random_n_sims: int = 1000,
) -> dict:
    """単一仮説を単一シンボルで実行し、結果dictを返す。

    全反証テストを実行し、bias_test_typeに応じて判定フラグを設定する。
    信号関数がエラーを出してもクラッシュしない。

    Args:
        hyp: HYPOTHESESの1エントリ
        df: データ準備済みDataFrame（マクロ/ペア列マージ済み）
        symbol: シンボル名
        shuffle_seed: シャッフルテスト再現用シード
        shuffle_n_perms: シャッフルテスト並替回数
        random_n_sims: ランダムデータ対照テストのシミュレーション回数

    Returns:
        record_result()に渡せる結果dict
    """
    hyp_id = hyp["id"]
    direction = hyp["direction"]
    bias_test_type = hyp["bias_test_type"]
    timeframe = hyp["timeframe"]

    base_result = {
        "id": hyp_id,
        "agent": "signal_runner",
        "category": hyp["category"],
        "hypothesis": hyp_id,
        "direction": direction,
        "symbols_tested": symbol,
        "regime_condition": "",
        "holding_period": "next_bar",
        "source": "signal_defs.py",
    }

    # 1. シグナル生成
    try:
        signal = hyp["func"](df)
    except Exception as e:
        logger.warning("H %s / %s: シグナル生成エラー: %s", hyp_id, symbol, e)
        return {
            **base_result,
            "n_samples": 0,
            "metric_name": "error",
            "metric_value": 0.0,
            "pvalue": None,
            "raw_detail": f"Error in signal function: {type(e).__name__}: {e}",
            "passed": False,
            "refute_shuffle_pvalue": None,
            "refute_random_data_fp_rate": None,
            "refute_reverse_direction_diff": None,
            "refute_period_exclusion_survived": None,
        }

    # 2. リターン計算
    returns = compute_next_returns(df, timeframe)

    # 3. Stage 1 スクリーニング
    try:
        screen_result = screen_signal(returns, signal, direction)
    except Exception as e:
        logger.warning("H %s / %s: screen_signalエラー: %s", hyp_id, symbol, e)
        return {
            **base_result,
            "n_samples": 0,
            "metric_name": "error",
            "metric_value": 0.0,
            "pvalue": None,
            "raw_detail": f"Error in screen_signal: {type(e).__name__}: {e}",
            "passed": False,
            "refute_shuffle_pvalue": None,
            "refute_random_data_fp_rate": None,
            "refute_reverse_direction_diff": None,
            "refute_period_exclusion_survived": None,
        }

    # 4. 反証テスト（全4種を実行。判定はbias_test_type + signal型に応じて）
    #
    # float信号（Spearman相関で評価）に対して不適切なテスト:
    #   - random_data_control: FP率が常に~50%（ランダムリターンとの相関が正になる確率）
    #   - reverse_direction_test: Spearman rは方向ラベルに依存しない（diff=0が正常）
    # → 全テストを実行しデータは記録するが、float信号ではこの2つを判定から除外する
    is_bool_signal = pd.api.types.is_bool_dtype(signal) or (
        pd.api.types.is_integer_dtype(signal)
        and set(signal.dropna().unique()).issubset({0, 1})
    )

    refutation_results: dict[str, RefutationResult | None] = {
        "shuffle": None,
        "random_data": None,
        "reverse_direction": None,
        "period_exclusion": None,
    }

    if screen_result.n_samples >= 30:
        try:
            refutation_results["shuffle"] = shuffle_test(
                returns, signal, direction, n_perms=shuffle_n_perms, rng_seed=shuffle_seed
            )
        except Exception as e:
            logger.warning("H %s / %s: shuffle_testエラー: %s", hyp_id, symbol, e)

        try:
            refutation_results["random_data"] = random_data_control(
                signal, direction, n_sims=random_n_sims, rng_seed=shuffle_seed
            )
        except Exception as e:
            logger.warning("H %s / %s: random_data_controlエラー: %s", hyp_id, symbol, e)

        try:
            refutation_results["reverse_direction"] = reverse_direction_test(returns, signal)
        except Exception as e:
            logger.warning("H %s / %s: reverse_direction_testエラー: %s", hyp_id, symbol, e)

        try:
            refutation_results["period_exclusion"] = period_exclusion_test(
                returns, signal, direction
            )
        except Exception as e:
            logger.warning("H %s / %s: period_exclusion_testエラー: %s", hyp_id, symbol, e)

    # 5. 判定: screen通過 + 判定対象の反証テスト全通過
    judge_tests = list(REFUTATION_JUDGE_MAP[bias_test_type])
    if not is_bool_signal:
        # float信号: random_data と reverse_direction は判定対象外
        judge_tests = [t for t in judge_tests if t not in ("random_data", "reverse_direction")]

    refutation_passed = all(
        refutation_results[t] is not None and refutation_results[t].passed
        for t in judge_tests
        if refutation_results[t] is not None
    )
    # N < 30 の場合は反証テスト未実行 → 反証による脱落はなし（screen_signalの不合格で落ちる）
    if screen_result.n_samples < 30:
        refutation_passed = True

    passed = screen_result.passed and refutation_passed

    # 6. 結果dict構築
    return {
        **base_result,
        "n_samples": screen_result.n_samples,
        "metric_name": screen_result.metric_name,
        "metric_value": screen_result.metric_value,
        "pvalue": screen_result.pvalue,
        "raw_detail": screen_result.raw_detail,
        "passed": passed,
        # 反証テスト結果（全4種。実行されなかった場合はNone）
        "refute_shuffle_pvalue": (
            refutation_results["shuffle"].pvalue
            if refutation_results["shuffle"] is not None else None
        ),
        "refute_shuffle_passed": (
            refutation_results["shuffle"].passed
            if refutation_results["shuffle"] is not None else None
        ),
        "refute_random_data_fp_rate": (
            refutation_results["random_data"].metric_value
            if refutation_results["random_data"] is not None else None
        ),
        "refute_random_data_passed": (
            refutation_results["random_data"].passed
            if refutation_results["random_data"] is not None else None
        ),
        "refute_reverse_direction_diff": (
            refutation_results["reverse_direction"].metric_value
            if refutation_results["reverse_direction"] is not None else None
        ),
        "refute_reverse_direction_passed": (
            refutation_results["reverse_direction"].passed
            if refutation_results["reverse_direction"] is not None else None
        ),
        "refute_period_exclusion_survived": (
            refutation_results["period_exclusion"].metric_value
            if refutation_results["period_exclusion"] is not None else None
        ),
        "refute_period_exclusion_passed": (
            refutation_results["period_exclusion"].passed
            if refutation_results["period_exclusion"] is not None else None
        ),
        "bias_test_type": bias_test_type,
        "signal_dtype": "bool" if is_bool_signal else "float",
    }


# ── メインループ ──


def run_all(
    hypotheses: list[dict] | None = None,
    daily_dir: Path | str = DEFAULT_DAILY_DIR,
    intraday_dir: Path | str = DEFAULT_INTRADAY_DIR,
    macro_dir: Path | str = DEFAULT_MACRO_DIR,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
    shuffle_n_perms: int = 1000,
    random_n_sims: int = 1000,
) -> list[dict]:
    """全仮説×全対象シンボルを実行し、結果をCSVに記録する。

    Args:
        hypotheses: HYPOTHESESリスト（デフォルト: signal_defs.HYPOTHESES）
        daily_dir: 日足ディレクトリ
        intraday_dir: 5分足ディレクトリ
        macro_dir: マクロディレクトリ
        output_path: 結果CSV出力先
        shuffle_n_perms: シャッフルテスト並替回数
        random_n_sims: ランダムデータ対照テストのシミュレーション回数

    Returns:
        全結果dictのリスト
    """
    if hypotheses is None:
        hypotheses = HYPOTHESES

    all_results: list[dict] = []
    total = len(hypotheses)
    t0 = time.time()

    # データキャッシュ（同じシンボル×timeframeの再読み込みを避ける）
    _cache_daily: dict[str, pd.DataFrame] = {}
    _cache_intraday: dict[str, pd.DataFrame] = {}

    for i, hyp in enumerate(hypotheses):
        hyp_id = hyp["id"]
        timeframe = hyp["timeframe"]
        requires_macro = hyp.get("requires_macro", [])
        requires_pair = hyp.get("requires_pair", False)
        category = hyp.get("category", 0)

        # 対象シンボル決定
        if timeframe == "intraday":
            symbols = SYMBOLS_INTRADAY
        else:
            symbols = SYMBOLS_DAILY

        for symbol in symbols:
            # データ読み込み（キャッシュ利用）
            try:
                if timeframe == "intraday":
                    if symbol not in _cache_intraday:
                        _cache_intraday[symbol] = load_polygon_5min(
                            symbol, data_dir=intraday_dir, daily_dir=daily_dir
                        )
                    df = _cache_intraday[symbol].copy()
                else:
                    if symbol not in _cache_daily:
                        _cache_daily[symbol] = load_daily(symbol, data_dir=daily_dir)
                    df = _cache_daily[symbol].copy()
            except FileNotFoundError:
                logger.warning("H %s / %s: データファイルなし。スキップ", hyp_id, symbol)
                continue

            # マクロマージ
            if requires_macro:
                df = merge_macro(df, requires_macro, macro_dir=macro_dir)

            # ペアマージ
            if requires_pair:
                pair_sym = resolve_pair_symbol(symbol, category)
                if pair_sym is None:
                    logger.info("H %s / %s: ペアマッピングなし。スキップ", hyp_id, symbol)
                    continue
                df = merge_pair(df, pair_sym, daily_dir=daily_dir,
                                intraday_dir=intraday_dir, timeframe=timeframe)

            # 実行
            result = run_hypothesis(
                hyp, df, symbol,
                shuffle_n_perms=shuffle_n_perms,
                random_n_sims=random_n_sims,
            )
            all_results.append(result)

            # CSV記録
            try:
                record_result(result, output_path=output_path)
            except Exception as e:
                logger.error("CSV記録エラー: %s", e)

        if (i + 1) % 50 == 0 or i == total - 1:
            elapsed = time.time() - t0
            logger.info(
                "進捗: %d/%d 仮説完了 (%.1f秒経過)", i + 1, total, elapsed
            )

    elapsed = time.time() - t0
    n_passed = sum(1 for r in all_results if r.get("passed"))
    logger.info(
        "完了: %d件実行, %d件通過 (%.1f秒)",
        len(all_results), n_passed, elapsed,
    )
    return all_results


# ── CLI ──

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Signal Runner - Round 1 機械実行")
    parser.add_argument("--dry-run", action="store_true", help="実行せず仮説数を表示")
    parser.add_argument("--shuffle-perms", type=int, default=1000, help="シャッフル並替回数")
    parser.add_argument("--random-sims", type=int, default=1000, help="ランダムデータシミュレーション回数")
    args = parser.parse_args()

    if args.dry_run:
        from collections import Counter
        tf_counts = Counter(h["timeframe"] for h in HYPOTHESES)
        print(f"仮説数: {len(HYPOTHESES)}")
        print(f"  daily: {tf_counts['daily']} × {len(SYMBOLS_DAILY)} symbols")
        print(f"  daily_macro: {tf_counts['daily_macro']} × {len(SYMBOLS_DAILY)} symbols")
        print(f"  intraday: {tf_counts['intraday']} × {len(SYMBOLS_INTRADAY)} symbols")
        total_runs = (
            tf_counts["daily"] * len(SYMBOLS_DAILY)
            + tf_counts["daily_macro"] * len(SYMBOLS_DAILY)
            + tf_counts["intraday"] * len(SYMBOLS_INTRADAY)
        )
        print(f"  合計実行数: {total_runs}")
    else:
        results = run_all(
            shuffle_n_perms=args.shuffle_perms,
            random_n_sims=args.random_sims,
        )
