"""エントリーシグナル研究ユーティリティ

4並列Agentが仮説検証に使用する共通ライブラリ。
ADR-013の3段階ファネルとADR-014のスプリット調整を実装。

全関数はステートレス（入力DataFrameから結果を返す）。
唯一の副作用はrecord_result()のCSV追記。

データ参照先:
  Polygon 5分足: ../master_sensei/data/research/polygon_intraday/
  日足(AdjClose含む): ../master_sensei/data/parquet/daily/
  ※ master_sensei/ は読み取り専用。このブランチ(master_sensei_1000_idea)には
    data/parquet/ が存在しない(.gitignore除外)ため、master_sensei側を参照する。
"""
from __future__ import annotations

import csv
import fcntl
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── 定数 ──

DEFAULT_INTRADAY_DIR = Path(__file__).resolve().parent.parent / ".." / "master_sensei" / "data" / "research" / "polygon_intraday"
DEFAULT_DAILY_DIR = Path(__file__).resolve().parent.parent / ".." / "master_sensei" / "data" / "parquet" / "daily"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "research" / "signal_ideas.csv"

REGULAR_SESSION_START = "09:30"
REGULAR_SESSION_END = "15:55"


# ── データクラス ──


@dataclass
class SignalTestResult:
    """Stage 1/2のテスト結果"""

    passed: bool
    n_samples: int
    metric_name: str
    metric_value: float
    pvalue: float | None
    raw_detail: str


@dataclass
class RefutationResult:
    """反証テストの結果"""

    test_name: str
    passed: bool  # True = シグナルは反証されなかった（良い）
    metric_value: float
    pvalue: float | None
    detail: str


# ── データ読み込み ──


def load_daily(
    symbol: str,
    data_dir: Path | str = DEFAULT_DAILY_DIR,
) -> pd.DataFrame:
    """日足Parquetを読み込む。

    Args:
        symbol: ティッカー (例: "SOXL")
        data_dir: 日足Parquetディレクトリ

    Returns:
        DataFrame (index=Date, columns=[Open, High, Low, Close, Volume, AdjClose, ...])

    Raises:
        FileNotFoundError: Parquetファイルが存在しない
    """
    path = Path(data_dir) / f"{symbol}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"日足Parquetが見つかりません: {path}")
    return pd.read_parquet(path)


def load_polygon_5min(
    symbol: str,
    data_dir: Path | str = DEFAULT_INTRADAY_DIR,
    daily_dir: Path | str = DEFAULT_DAILY_DIR,
    session: Literal["regular", "all"] = "regular",
) -> pd.DataFrame:
    """Polygon 5分足を読み込み、スプリット調整を適用する（ADR-014）。

    調整係数 = 日足AdjClose / Close（日付ごと）。
    日足が存在しないシンボル（クロスアセットETF等）は係数1.0。

    Args:
        symbol: ティッカー (例: "SOXL")
        data_dir: Polygon 5分足Parquetディレクトリ
        daily_dir: 日足Parquetディレクトリ（スプリット調整用）
        session: "regular" = 09:30-15:55 ETのみ, "all" = 全セッション

    Returns:
        スプリット調整済みDataFrame
        (index=datetime[ET], columns=[Open, High, Low, Close, Volume, VWAP, NumTrades])

    Raises:
        FileNotFoundError: 5分足Parquetが存在しない
    """
    intraday_path = Path(data_dir) / f"{symbol}_5min.parquet"
    if not intraday_path.exists():
        raise FileNotFoundError(f"5分足Parquetが見つかりません: {intraday_path}")

    df = pd.read_parquet(intraday_path)

    # スプリット調整係数を算出（ADR-014）
    daily_path = Path(daily_dir) / f"{symbol}.parquet"
    if daily_path.exists():
        daily = pd.read_parquet(daily_path)
        # factor = AdjClose / Close（日付ごと）。キーはPython dateで統一
        # （日足indexはnaive、5分足indexはtz-awareのため）
        factor_map: dict = {}
        for idx, row in daily.iterrows():
            d = idx.date() if hasattr(idx, "date") else idx
            if row["Close"] != 0:
                factor_map[d] = row["AdjClose"] / row["Close"]

        # 5分足の日付(Python date)にマッピング
        bar_dates = [ts.date() for ts in df.index]
        factors = np.array([factor_map.get(d, 1.0) for d in bar_dates])

        # OHLC + VWAP に係数を乗じる
        for col in ("Open", "High", "Low", "Close", "VWAP"):
            if col in df.columns:
                df[col] = df[col].values * factors

        # Volume は逆数（株数が増えるので調整前の出来高を係数で割る）
        if "Volume" in df.columns:
            df["Volume"] = df["Volume"].values / factors
    else:
        logger.info(
            "%s: 日足ファイルなし。スプリット調整スキップ（係数1.0）", symbol
        )

    # セッションフィルタ
    if session == "regular":
        df = df.between_time(REGULAR_SESSION_START, REGULAR_SESSION_END)

    return df


# ── Stage 1: スクリーニング ──


def screen_signal(
    returns: pd.Series,
    signal: pd.Series,
    direction: Literal["long", "short"],
) -> SignalTestResult:
    """Stage 1 スクリーニング（ADR-013: 偽陰性回避）。

    bool型シグナル: 発火時のリターン方向一致率 > 50%
    float型シグナル: Spearman相関が direction と一致する符号

    Args:
        returns: リターン系列（次バーリターン等）
        signal: シグナル系列（bool or float）。共通indexで揃えること
        direction: "long" = 正リターン期待, "short" = 負リターン期待

    Returns:
        SignalTestResult (passed, n_samples, metric_name, metric_value, pvalue, raw_detail)
    """
    from scipy import stats as sp_stats

    # index を揃えてNaN除去
    common = returns.index.intersection(signal.index)
    r = returns.loc[common].dropna()
    s = signal.loc[common].reindex(r.index).dropna()
    r = r.reindex(s.index)

    is_bool = pd.api.types.is_bool_dtype(s) or (
        pd.api.types.is_integer_dtype(s) and set(s.unique()).issubset({0, 1})
    )

    if is_bool:
        s_bool = s.astype(bool)
        fired = r[s_bool]
        n = len(fired)

        if n < 30:
            return SignalTestResult(
                passed=False,
                n_samples=n,
                metric_name="direction_agreement",
                metric_value=0.0,
                pvalue=None,
                raw_detail=f"N={n} < 30: サンプル不足",
            )

        if direction == "long":
            agree = (fired > 0).sum() / n
        else:
            agree = (fired < 0).sum() / n

        # 二項検定: H0=一致率50%
        successes = int(agree * n)
        btest = sp_stats.binomtest(successes, n, 0.5, alternative="greater")
        pvalue = btest.pvalue

        return SignalTestResult(
            passed=bool(agree > 0.50),
            n_samples=n,
            metric_name="direction_agreement",
            metric_value=float(agree),
            pvalue=float(pvalue),
            raw_detail=f"一致率={agree:.3f}, N={n}, direction={direction}",
        )
    else:
        # float信号: Spearman相関
        n = len(r)
        if n < 30:
            return SignalTestResult(
                passed=False,
                n_samples=n,
                metric_name="spearman_r",
                metric_value=0.0,
                pvalue=None,
                raw_detail=f"N={n} < 30: サンプル不足",
            )

        corr, pvalue = sp_stats.spearmanr(s, r)

        if direction == "long":
            passed = bool(corr > 0)
        else:
            passed = bool(corr < 0)

        return SignalTestResult(
            passed=passed,
            n_samples=n,
            metric_name="spearman_r",
            metric_value=float(corr),
            pvalue=float(pvalue),
            raw_detail=f"Spearman r={corr:.4f}, p={pvalue:.4f}, direction={direction}",
        )


# ── Stage 2: 統計検証 ──


def bh_correction(
    pvalues: list[float] | np.ndarray,
    alpha: float = 0.20,
) -> np.ndarray:
    """Benjamini-Hochberg FDR制御（ADR-013 Stage 2）。

    Args:
        pvalues: p値のリスト
        alpha: FDR制御水準（デフォルト0.20）

    Returns:
        bool配列（入力と同じ順序。Trueなら生き残り）
    """
    pv = np.asarray(pvalues, dtype=float)
    m = len(pv)
    if m == 0:
        return np.array([], dtype=bool)

    # BH手順: ソートしてrank/m * alphaと比較
    sorted_idx = np.argsort(pv)
    sorted_pv = pv[sorted_idx]
    thresholds = np.arange(1, m + 1) / m * alpha

    # 最大のk where p(k) <= threshold(k) を見つけ、k以下は全て棄却
    below = sorted_pv <= thresholds
    if not below.any():
        return np.zeros(m, dtype=bool)

    max_k = np.max(np.where(below)[0])
    rejected_sorted = np.zeros(m, dtype=bool)
    rejected_sorted[: max_k + 1] = True

    # 元の順序に戻す
    result = np.zeros(m, dtype=bool)
    result[sorted_idx] = rejected_sorted
    return result


def walk_forward_test(
    returns: pd.Series,
    signal: pd.Series,
    direction: Literal["long", "short"],
    n_splits: int = 2,
) -> SignalTestResult:
    """Walk-forward検証（ADR-013 Stage 2: 過適合防止）。

    データを時系列で n_splits 分割し、各セグメントで screen_signal を実行。
    全セグメントでシグナルの方向が一致すれば合格。

    Args:
        returns: リターン系列
        signal: シグナル系列
        direction: "long" or "short"
        n_splits: 分割数（デフォルト2）

    Returns:
        SignalTestResult
    """
    common = returns.index.intersection(signal.index)
    r = returns.loc[common].sort_index()
    s = signal.loc[common].sort_index()

    split_size = len(r) // n_splits
    if split_size < 30:
        return SignalTestResult(
            passed=False,
            n_samples=len(r),
            metric_name="walk_forward",
            metric_value=0.0,
            pvalue=None,
            raw_detail=f"分割サイズ={split_size} < 30: 各セグメントのサンプル不足",
        )

    results = []
    for i in range(n_splits):
        start = i * split_size
        end = (i + 1) * split_size if i < n_splits - 1 else len(r)
        seg_r = r.iloc[start:end]
        seg_s = s.iloc[start:end]
        seg_result = screen_signal(seg_r, seg_s, direction)
        results.append(seg_result)

    all_passed = all(res.passed for res in results)
    details = [
        f"Split {i+1}: passed={res.passed}, metric={res.metric_value:.3f}"
        for i, res in enumerate(results)
    ]

    return SignalTestResult(
        passed=all_passed,
        n_samples=len(r),
        metric_name="walk_forward",
        metric_value=sum(1 for r in results if r.passed) / len(results),
        pvalue=None,
        raw_detail=f"{n_splits} splits: {'; '.join(details)}",
    )


def regime_stability_test(
    returns: pd.Series,
    signal: pd.Series,
    direction: Literal["long", "short"],
    regime_labels: pd.Series,
) -> SignalTestResult:
    """レジーム安定性テスト（ADR-013 Stage 2: レジーム依存排除）。

    2レジーム以上で同方向にシグナルが有効であれば合格。
    N < 30 のレジームグループはスキップ。

    Args:
        returns: リターン系列
        signal: シグナル系列
        direction: "long" or "short"
        regime_labels: レジームラベル系列（同じindex）

    Returns:
        SignalTestResult
    """
    common = returns.index.intersection(signal.index).intersection(regime_labels.index)
    r = returns.loc[common]
    s = signal.loc[common]
    reg = regime_labels.loc[common]

    regime_results = {}
    for regime_name in reg.unique():
        mask = reg == regime_name
        seg_r = r[mask]
        seg_s = s[mask]

        # screen_signal に委ねる。N<30 なら screen_signal が passed=False を返す
        result = screen_signal(seg_r, seg_s, direction)

        # screen_signal が N<30 で不合格 → テスト不能としてスキップ扱い
        if result.n_samples < 30:
            regime_results[regime_name] = None
            continue
        regime_results[regime_name] = result

    tested = {k: v for k, v in regime_results.items() if v is not None}
    passed_regimes = [k for k, v in tested.items() if v.passed]

    passed = len(passed_regimes) >= 2
    details = []
    for k, v in regime_results.items():
        if v is None:
            details.append(f"{k}: skipped (N<30)")
        else:
            details.append(f"{k}: passed={v.passed}, metric={v.metric_value:.3f}")

    return SignalTestResult(
        passed=passed,
        n_samples=len(r),
        metric_name="regime_stability",
        metric_value=len(passed_regimes) / max(len(tested), 1),
        pvalue=None,
        raw_detail=f"regimes: {'; '.join(details)}",
    )


def multi_symbol_test(
    symbol_results: dict[str, SignalTestResult],
) -> SignalTestResult:
    """複数銘柄再現テスト（ADR-013 Stage 2: 銘柄固有ノイズ排除）。

    2銘柄以上で screen_signal が passed なら合格。

    Args:
        symbol_results: {symbol: SignalTestResult} の辞書

    Returns:
        SignalTestResult
    """
    if not symbol_results:
        return SignalTestResult(
            passed=False,
            n_samples=0,
            metric_name="multi_symbol",
            metric_value=0.0,
            pvalue=None,
            raw_detail="入力なし",
        )

    passed_symbols = [k for k, v in symbol_results.items() if v.passed]
    total_n = sum(v.n_samples for v in symbol_results.values())

    details = [
        f"{k}: passed={v.passed}, metric={v.metric_value:.3f}"
        for k, v in symbol_results.items()
    ]

    return SignalTestResult(
        passed=len(passed_symbols) >= 2,
        n_samples=total_n,
        metric_name="multi_symbol",
        metric_value=len(passed_symbols) / len(symbol_results),
        pvalue=None,
        raw_detail=f"symbols: {'; '.join(details)}",
    )


# ── 反証テスト（ADR-013 バイアス対策） ──


def shuffle_test(
    returns: pd.Series,
    signal: pd.Series,
    direction: Literal["long", "short"],
    n_perms: int = 1000,
    rng_seed: int | None = None,
) -> RefutationResult:
    """シャッフルテスト（並替テスト）。

    シグナルの日付をランダムに並替えて同じメトリクスを計算。
    観測値が並替分布の中で極端であればシグナルは実在（反証されない）。

    Args:
        returns: リターン系列
        signal: シグナル系列（bool）
        direction: "long" or "short"
        n_perms: 並替回数
        rng_seed: 再現性用シード

    Returns:
        RefutationResult (passed=True ならシグナルは反証されなかった)
    """
    common = returns.index.intersection(signal.index)
    r = returns.loc[common].dropna()
    s = signal.loc[common].reindex(r.index).dropna()
    r = r.reindex(s.index)

    # 定数シグナル検出（シャッフルが無意味な場合）
    if s.nunique() == 1:
        logger.warning(
            "shuffle_test: シグナルが定数（全%s）。シャッフルは無意味です。", s.iloc[0]
        )
        return RefutationResult(
            test_name="shuffle",
            passed=False,
            metric_value=0.0,
            pvalue=1.0,
            detail="シグナルが定数: シャッフルはno-op",
        )

    # 観測メトリクス
    observed = screen_signal(r, s, direction)
    obs_metric = observed.metric_value

    # 並替テスト
    rng = np.random.default_rng(rng_seed)
    s_values = s.values.copy()
    perm_metrics = np.empty(n_perms)

    for i in range(n_perms):
        rng.shuffle(s_values)
        perm_signal = pd.Series(s_values.copy(), index=s.index)
        perm_result = screen_signal(r, perm_signal, direction)
        perm_metrics[i] = perm_result.metric_value

    # p値: Phipson & Smyth (2010) — 観測値自体を1つの並替として含める
    # 最小p値 = 1/(n_perms+1)。p=0.0 は返らない
    pvalue = float(((perm_metrics >= obs_metric).sum() + 1) / (n_perms + 1))
    passed = pvalue < 0.05

    return RefutationResult(
        test_name="shuffle",
        passed=passed,
        metric_value=obs_metric,
        pvalue=pvalue,
        detail=f"observed={obs_metric:.4f}, perm_mean={perm_metrics.mean():.4f}, p={pvalue:.4f}",
    )


def random_data_control(
    signal: pd.Series,
    direction: Literal["long", "short"],
    n_sims: int = 1000,
    rng_seed: int | None = None,
) -> RefutationResult:
    """ランダムデータ対照テスト。

    既知のランダムリターン系列に対してシグナルを適用。
    偽陽性率（screen_signalがpassedになる率）が低ければ合格。

    Args:
        signal: シグナル系列
        direction: "long" or "short"
        n_sims: シミュレーション回数
        rng_seed: 再現性用シード

    Returns:
        RefutationResult (passed=True なら偽陽性率が低い)
    """
    rng = np.random.default_rng(rng_seed)
    n = len(signal)
    fp_count = 0

    for _ in range(n_sims):
        random_returns = pd.Series(
            rng.normal(0.0, 0.02, n), index=signal.index
        )
        result = screen_signal(random_returns, signal, direction)
        if result.passed:
            fp_count += 1

    fp_rate = fp_count / n_sims
    passed = fp_rate < 0.10

    return RefutationResult(
        test_name="random_data",
        passed=passed,
        metric_value=fp_rate,
        pvalue=None,
        detail=f"偽陽性率={fp_rate:.3f} ({fp_count}/{n_sims})",
    )


def reverse_direction_test(
    returns: pd.Series,
    signal: pd.Series,
) -> RefutationResult:
    """逆方向テスト。

    long と short の両方向で screen_signal を実行。
    一方のみ有効（非対称）であれば合格。両方向で同等に機能するならノイズ。

    Args:
        returns: リターン系列
        signal: シグナル系列

    Returns:
        RefutationResult (passed=True なら非対称 = 反証されなかった)
    """
    long_result = screen_signal(returns, signal, "long")
    short_result = screen_signal(returns, signal, "short")

    # 非対称性: 方向一致率の差
    diff = abs(long_result.metric_value - short_result.metric_value)
    passed = diff > 0.05

    return RefutationResult(
        test_name="reverse_direction",
        passed=passed,
        metric_value=diff,
        pvalue=None,
        detail=(
            f"long={long_result.metric_value:.3f}, "
            f"short={short_result.metric_value:.3f}, diff={diff:.3f}"
        ),
    )


def period_exclusion_test(
    returns: pd.Series,
    signal: pd.Series,
    direction: Literal["long", "short"],
    exclude_fractions: list[float] | None = None,
) -> RefutationResult:
    """期間除外テスト。

    シグナル発火時のリターンへの貢献が大きいバーを除外し、
    シグナルが生き残るかチェック。少数の極端イベント依存を検出。

    Args:
        returns: リターン系列
        signal: シグナル系列
        direction: "long" or "short"
        exclude_fractions: 除外する上位割合のリスト（デフォルト [0.1, 0.2]）

    Returns:
        RefutationResult (passed=True なら除外後もシグナル有効)
    """
    if exclude_fractions is None:
        exclude_fractions = [0.1, 0.2]

    common = returns.index.intersection(signal.index)
    r = returns.loc[common].dropna()
    s = signal.loc[common].reindex(r.index).dropna()
    r = r.reindex(s.index)

    # シグナル発火時のリターン
    is_bool = pd.api.types.is_bool_dtype(s) or (
        pd.api.types.is_integer_dtype(s) and set(s.unique()).issubset({0, 1})
    )
    if is_bool:
        fired_mask = s.astype(bool)
    else:
        fired_mask = pd.Series(True, index=s.index)

    fired_returns = r[fired_mask]

    # 貢献度でソート（方向に応じて）
    if direction == "long":
        contribution = fired_returns  # 大きい正リターンが貢献大
    else:
        contribution = -fired_returns  # 大きい負リターンが貢献大

    sorted_idx = contribution.sort_values(ascending=False).index

    all_survived = True
    details = []

    for frac in exclude_fractions:
        n_exclude = max(1, int(len(sorted_idx) * frac))
        exclude_dates = sorted_idx[:n_exclude]

        remaining_r = r.drop(exclude_dates)
        remaining_s = s.drop(exclude_dates)

        if len(remaining_r[remaining_s.astype(bool) if is_bool else remaining_s.index]) < 30:
            details.append(f"frac={frac}: N不足でスキップ")
            continue

        result = screen_signal(remaining_r, remaining_s, direction)
        details.append(
            f"frac={frac}: passed={result.passed}, "
            f"metric={result.metric_value:.3f} (除外{n_exclude}バー)"
        )
        if not result.passed:
            all_survived = False

    return RefutationResult(
        test_name="period_exclusion",
        passed=all_survived,
        metric_value=1.0 if all_survived else 0.0,
        pvalue=None,
        detail="; ".join(details),
    )


# ── 検出力分析 (Power Analysis) ──


def compute_mde_binomial(
    n: int,
    alpha: float = 0.20,
    power: float = 0.80,
) -> float:
    """二項検定のMDE（最小検出可能効果）を算出する。

    H0: p = 0.50（ランダム）に対する片側検定で、
    検出力 >= power となる最小の方向一致率 p_min を返す。

    scipy.stats.binomtest を使った exact 計算。
    bisect で p_min を探索する（正規近似より小サンプルで正確）。

    Args:
        n: サンプル数（発火回数）
        alpha: 有意水準（片側）
        power: 要求する検出力

    Returns:
        MDE（最小検出可能な方向一致率）。0.50超の値。

    Raises:
        ValueError: n < 1 or alpha/power ∉ (0, 1)
    """
    from scipy import stats as sp_stats

    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if not (0 < alpha < 1):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if not (0 < power < 1):
        raise ValueError(f"power must be in (0, 1), got {power}")

    # 棄却域の臨界値 k_crit: binom.isf(alpha, n, 0.5) は
    # P(X > k_crit | p=0.5) <= alpha を満たす最小整数を返す。
    # 棄却条件は X > k_crit（= X >= k_crit+1）。
    # 検出力 = P(X > k_crit | p=p1) = binom.sf(k_crit, n, p1)
    from scipy.stats import binom
    k_crit = int(binom.isf(alpha, n, 0.5))

    def _power_at(p1: float) -> float:
        """p=p1 のとき H0 を棄却する確率（検出力）"""
        return float(binom.sf(k_crit, n, p1))

    # bisect: power_at(p1) = power となる p1 を探索
    lo, hi = 0.50 + 1e-10, 1.0 - 1e-10
    for _ in range(100):  # 二分法 100 回で十分な精度
        mid = (lo + hi) / 2
        if _power_at(mid) < power:
            lo = mid
        else:
            hi = mid

    return round(hi, 6)


def compute_mde_spearman(
    n: int,
    alpha: float = 0.20,
    power: float = 0.80,
) -> float:
    """Spearman相関のMDE（最小検出可能効果）を算出する。

    Fisher z変換による解析解:
      r_min = tanh((z_alpha + z_beta) / sqrt(N - 3))

    片側検定を仮定（direction で符号を指定するため）。

    Args:
        n: サンプル数
        alpha: 有意水準（片側）
        power: 要求する検出力

    Returns:
        MDE（最小検出可能な |r|）

    Note:
        Fisher z 変換は厳密には Pearson 相関向け。Spearman 相関への適用は
        連続・近似正規分布を仮定した場合の近似値。金融リターンの fat-tail 分布
        下では小サンプル(N<100)で検出力が過大評価される可能性がある。

    Raises:
        ValueError: n < 4 (Fisher z で N-3 >= 1 が必要)
    """
    from scipy.stats import norm

    if n < 4:
        raise ValueError(f"n must be >= 4 for Fisher z transform, got {n}")
    if not (0 < alpha < 1):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if not (0 < power < 1):
        raise ValueError(f"power must be in (0, 1), got {power}")

    z_alpha = norm.ppf(1 - alpha)
    z_beta = norm.ppf(power)
    z_r = (z_alpha + z_beta) / np.sqrt(n - 3)
    r_min = float(np.tanh(z_r))

    return round(r_min, 6)


def power_analysis_report(
    symbols: list[str],
    data_dir: Path | str = DEFAULT_INTRADAY_DIR,
    daily_dir: Path | str = DEFAULT_DAILY_DIR,
    alpha: float = 0.20,
    power: float = 0.80,
    n_splits: int = 2,
) -> pd.DataFrame:
    """シンボル別の検出力分析レポートを生成する。

    各シンボルの Polygon 5分足を読み込み、
    日単位・バー単位・walk-forward分割でのMDEを算出する。

    Args:
        symbols: ティッカーリスト
        data_dir: Polygon 5分足ディレクトリ
        daily_dir: 日足ディレクトリ（スプリット調整用）
        alpha: 有意水準
        power: 要求検出力
        n_splits: walk-forward分割数

    Returns:
        DataFrame (columns: symbol, n_days, n_bars,
                   mde_binomial_daily, mde_spearman_daily,
                   mde_binomial_bar, mde_spearman_bar,
                   mde_binomial_wf, mde_spearman_wf)
    """
    if not symbols:
        return pd.DataFrame()

    rows = []
    for sym in symbols:
        try:
            df = load_polygon_5min(sym, data_dir=data_dir, daily_dir=daily_dir,
                                   session="regular")
        except FileNotFoundError:
            logger.warning("power_analysis_report: %s のデータが見つかりません", sym)
            continue

        n_bars = len(df)
        # 営業日数 = ユニークな日付数
        n_days = len(set(ts.date() for ts in df.index))

        # walk-forward: 日単位でn_splits分割した各セグメントのN
        n_wf = n_days // n_splits

        row = {
            "symbol": sym,
            "n_days": n_days,
            "n_bars": n_bars,
            "mde_binomial_daily": compute_mde_binomial(max(n_days, 1), alpha, power),
            "mde_spearman_daily": compute_mde_spearman(max(n_days, 4), alpha, power),
            "mde_binomial_bar": compute_mde_binomial(max(n_bars, 1), alpha, power),
            "mde_spearman_bar": compute_mde_spearman(max(n_bars, 4), alpha, power),
            "mde_binomial_wf": (
                compute_mde_binomial(n_wf, alpha, power) if n_wf >= 1
                else float("nan")
            ),
            "mde_spearman_wf": (
                compute_mde_spearman(n_wf, alpha, power) if n_wf >= 4
                else float("nan")
            ),
        }
        rows.append(row)

    return pd.DataFrame(rows)


# ── 結果記録 ──

REQUIRED_COLUMNS = [
    "id", "agent", "category", "hypothesis", "direction",
    "symbols_tested", "n_samples", "metric_name", "metric_value",
    "pvalue", "regime_condition", "holding_period", "source", "raw_detail",
]


def record_result(
    result_dict: dict,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
) -> None:
    """検証結果をCSVに追記する（ADR-013: 全試行記録）。

    4 Agent並列書き込みに対応するため fcntl.flock で排他ロック。

    Args:
        result_dict: 結果辞書。REQUIRED_COLUMNS が全て必須。
            追加カラム（反証テスト結果等）も許容。
        output_path: 出力CSVパス

    Raises:
        ValueError: 必須カラムが不足
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in result_dict]
    if missing:
        raise ValueError(f"必須カラム不足: {missing}")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 全カラム（必須 + 追加）のヘッダを決定
    all_columns = list(result_dict.keys())

    with open(path, "a", newline="") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            # file_exists チェックはロック取得後に行う（TOCTOU防止���
            file_has_content = path.stat().st_size > 0
            writer = csv.DictWriter(
                f, fieldnames=all_columns, extrasaction="ignore"
            )
            if not file_has_content:
                writer.writeheader()
            writer.writerow(result_dict)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
