"""Stage 2 フィルタ（ADR-013: 統計的厳密性）

Stage 1通過仮説に対して4フィルタを適用:
  1. BH法補正後 p値 < 0.20（shuffle_test p値ベース）
  2. Walk-forward検証（2分割、各セグメントで方向一致）
  3. レジーム安定性（VIX 33%/67%百分位で3分類、2レジーム以上で一致）
  4. 複数銘柄再現（2銘柄以上で通過）

全フィルタ通過を Stage 2合格 とする。
落ちた単一銘柄仮説は Round 2候補として別記録。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from src.research_utils import (
    bh_correction,
    load_daily,
    load_polygon_5min,
    regime_stability_test,
    screen_signal,
    walk_forward_test,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VIX_PATH = ROOT / ".." / "master_sensei" / "data" / "parquet" / "macro" / "VIX.parquet"

# ── レジームラベル（VIX百分位ベース）──


def compute_vix_regimes(
    vix_series: pd.Series,
    low_percentile: float = 33.0,
    high_percentile: float = 67.0,
) -> pd.Series:
    """VIXの百分位でレジームを3分類する。

    Args:
        vix_series: VIX日次値のSeries（index=date）
        low_percentile: 低レジームの上限百分位
        high_percentile: 中レジームの上限百分位

    Returns:
        レジームラベルSeries（"low" / "mid" / "high"）
    """
    if vix_series.empty:
        return pd.Series([], dtype=object)

    low_th = np.nanpercentile(vix_series.values, low_percentile)
    high_th = np.nanpercentile(vix_series.values, high_percentile)

    def _label(v):
        if pd.isna(v):
            return None
        if v <= low_th:
            return "low"
        if v <= high_th:
            return "mid"
        return "high"

    return vix_series.apply(_label)


def load_vix_regime_labels(
    vix_path: Path | str = DEFAULT_VIX_PATH,
) -> pd.Series:
    """VIXパーケット読み込み→レジームラベル生成。

    Returns:
        Series (index=date, values=["low"/"mid"/"high"])
    """
    df = pd.read_parquet(vix_path)
    vix = df["value"] if "value" in df.columns else df.iloc[:, 0]
    return compute_vix_regimes(vix)


# ── フィルタ実装 ──


def apply_filter1_bh(
    shuffle_pvalues: pd.Series,
    alpha: float = 0.20,
) -> pd.Series:
    """Filter 1: BH法補正後 p値 < alpha。

    Args:
        shuffle_pvalues: shuffle_test p値のSeries（NaN含む）
        alpha: FDR閾値

    Returns:
        bool Series（True=通過）
    """
    result = pd.Series(False, index=shuffle_pvalues.index)
    mask = shuffle_pvalues.notna()
    if mask.sum() == 0:
        return result

    pv_valid = shuffle_pvalues[mask].values
    rejected = bh_correction(pv_valid, alpha=alpha)
    result.loc[mask] = rejected
    return result


def apply_filter4_multi_symbol(
    df: pd.DataFrame,
    pass_col: str = "passed_v2",
    min_symbols: int = 2,
) -> pd.DataFrame:
    """Filter 4: 複数銘柄再現。

    同じ仮説IDで min_symbols 以上のシンボルが通過している行をTrue。

    Args:
        df: signal_ideas形式のDataFrame
        pass_col: Stage 1通過フラグ列
        min_symbols: 最小シンボル数

    Returns:
        filter4_passed列を追加したDataFrame
    """
    result = df.copy()
    counts = df[df[pass_col] == True].groupby("id").size()
    passing_ids = set(counts[counts >= min_symbols].index)
    result["filter4_multi_symbol"] = result["id"].isin(passing_ids) & (result[pass_col] == True)
    return result


def compute_signal_and_returns(
    hyp: dict,
    symbol: str,
    daily_dir: Path | str,
    intraday_dir: Path | str,
    macro_dir: Path | str,
) -> tuple[pd.Series, pd.Series] | None:
    """仮説と銘柄からシグナル系列と次バーリターンを生成する。

    Returns:
        (signal, returns) or None（データなし/エラー時）
    """
    from src.signal_runner import merge_macro, merge_pair, resolve_pair_symbol

    try:
        if hyp["timeframe"] == "intraday":
            df = load_polygon_5min(symbol, data_dir=intraday_dir, daily_dir=daily_dir)
        else:
            df = load_daily(symbol, data_dir=daily_dir)
    except FileNotFoundError:
        return None

    if hyp.get("requires_macro"):
        df = merge_macro(df, hyp["requires_macro"], macro_dir=macro_dir)

    if hyp.get("requires_pair"):
        pair_sym = resolve_pair_symbol(symbol, hyp["category"])
        if pair_sym is None:
            return None
        df = merge_pair(df, pair_sym, daily_dir=daily_dir, intraday_dir=intraday_dir,
                        timeframe=hyp["timeframe"])

    try:
        signal = hyp["func"](df)
    except Exception as e:
        logger.warning("signal生成エラー %s/%s: %s", hyp["id"], symbol, e)
        return None

    returns = df["Close"].pct_change().shift(-1)
    return signal, returns


def apply_filter2_walk_forward(
    hyp: dict,
    symbol: str,
    daily_dir: Path | str,
    intraday_dir: Path | str,
    macro_dir: Path | str,
    n_splits: int = 2,
) -> bool:
    """Filter 2: Walk-forward検証。

    データを時系列でn_splits分割し、全セグメントで方向一致ならTrue。
    """
    pair = compute_signal_and_returns(hyp, symbol, daily_dir, intraday_dir, macro_dir)
    if pair is None:
        return False
    signal, returns = pair

    result = walk_forward_test(returns, signal, hyp["direction"], n_splits=n_splits)
    return result.passed


def apply_filter3_regime(
    hyp: dict,
    symbol: str,
    regime_labels: pd.Series,
    daily_dir: Path | str,
    intraday_dir: Path | str,
    macro_dir: Path | str,
) -> bool:
    """Filter 3: レジーム安定性。

    VIX 3レジームのうち2以上で方向一致ならTrue。
    """
    pair = compute_signal_and_returns(hyp, symbol, daily_dir, intraday_dir, macro_dir)
    if pair is None:
        return False
    signal, returns = pair

    # regime_labelsはdate index。signal/returnsのindexに合わせる
    if hasattr(signal.index, "date"):
        signal_dates = pd.Series(
            [ts.date() if hasattr(ts, "date") else ts for ts in signal.index],
            index=signal.index,
        )
    else:
        signal_dates = signal.index

    regime_map = {d: lbl for d, lbl in regime_labels.items()
                  if hasattr(d, "strftime")}
    # dateキーに変換
    regime_by_date = {}
    for d, lbl in regime_labels.items():
        key = d.date() if hasattr(d, "date") else d
        regime_by_date[key] = lbl

    aligned_regime = signal_dates.apply(lambda d: regime_by_date.get(d, None))
    aligned_regime.index = signal.index

    result = regime_stability_test(returns, signal, hyp["direction"], aligned_regime)
    return result.passed


# ── メインエントリポイント ──


def run_stage2(
    stage1_csv: Path | str,
    hypotheses: list[dict],
    daily_dir: Path | str,
    intraday_dir: Path | str,
    macro_dir: Path | str,
    vix_path: Path | str = DEFAULT_VIX_PATH,
    alpha: float = 0.20,
    n_wf_splits: int = 2,
    min_symbols: int = 2,
) -> pd.DataFrame:
    """Stage 2 全フィルタ適用。

    Returns:
        各仮説×シンボルの結果DataFrame
        (列: id, symbol, filter1_bh, filter2_wf, filter3_regime, filter4_multi, stage2_passed)
    """
    df = pd.read_csv(stage1_csv)
    logger.info("Stage 1結果読み込み: %d行", len(df))

    # Filter 1: BH補正（全行に適用、screen_signalのp値を使用）
    # shuffle_test p値は1/(n_perms+1)の離散制限でBHに不適合のため、screen_signal p値を使う
    logger.info("Filter 1: BH補正（alpha=%.2f, screen_signal p値使用）", alpha)
    screen_pv = df["pvalue"]
    df["filter1_bh_passed"] = apply_filter1_bh(screen_pv, alpha=alpha)
    n_f1 = df["filter1_bh_passed"].sum()
    logger.info("  通過: %d/%d", n_f1, len(df))

    # Stage 1通過 AND Filter 1通過 の行にFilter 2/3/4を適用
    candidates = df[(df["passed_v2"] == True) & (df["filter1_bh_passed"] == True)].copy()
    logger.info("Filter 2/3 候補: %d行", len(candidates))

    # hyp_by_id マップ
    hyp_by_id = {h["id"]: h for h in hypotheses}

    # Filter 2: Walk-forward
    logger.info("Filter 2: Walk-forward検証")
    f2_results = []
    for _, row in candidates.iterrows():
        hyp = hyp_by_id.get(row["id"])
        if hyp is None:
            f2_results.append(False)
            continue
        passed = apply_filter2_walk_forward(
            hyp, row["symbols_tested"], daily_dir, intraday_dir, macro_dir, n_splits=n_wf_splits
        )
        f2_results.append(passed)
    candidates["filter2_wf_passed"] = f2_results
    logger.info("  通過: %d/%d", sum(f2_results), len(f2_results))

    # Filter 3: Regime stability
    logger.info("Filter 3: レジーム安定性（VIX 3分類）")
    regime_labels = load_vix_regime_labels(vix_path)
    f3_results = []
    for _, row in candidates.iterrows():
        hyp = hyp_by_id.get(row["id"])
        if hyp is None:
            f3_results.append(False)
            continue
        passed = apply_filter3_regime(
            hyp, row["symbols_tested"], regime_labels,
            daily_dir, intraday_dir, macro_dir,
        )
        f3_results.append(passed)
    candidates["filter3_regime_passed"] = f3_results
    logger.info("  通過: %d/%d", sum(f3_results), len(f3_results))

    # 結果をdfにマージ
    df["filter2_wf_passed"] = False
    df["filter3_regime_passed"] = False
    df.loc[candidates.index, "filter2_wf_passed"] = candidates["filter2_wf_passed"]
    df.loc[candidates.index, "filter3_regime_passed"] = candidates["filter3_regime_passed"]

    # Filter 4: 複数銘柄再現
    logger.info("Filter 4: 複数銘柄再現（>=%d銘柄）", min_symbols)
    df = apply_filter4_multi_symbol(df, pass_col="passed_v2", min_symbols=min_symbols)
    n_f4 = df["filter4_multi_symbol"].sum()
    logger.info("  通過: %d", n_f4)

    # Stage 2最終判定: 全フィルタ通過
    df["stage2_passed"] = (
        (df["passed_v2"] == True)
        & df["filter1_bh_passed"]
        & df["filter2_wf_passed"]
        & df["filter3_regime_passed"]
        & df["filter4_multi_symbol"]
    )
    n_s2 = df["stage2_passed"].sum()
    logger.info("Stage 2最終通過: %d/%d", n_s2, len(df))

    return df
