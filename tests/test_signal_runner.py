"""signal_runner.py のテスト

4層構造: 既知解 → 境界 → 不変量 → 統合テスト
テスト対象: データ準備、リターン計算、反証テスト選択、結果記録
"""
from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


# ── テスト用ヘルパー ──


def _make_daily_df(n_days: int = 100, seed: int = 42) -> pd.DataFrame:
    """テスト用日足DataFrame。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=n_days, freq="B")
    close = 100.0 + np.cumsum(rng.normal(0, 1, n_days))
    return pd.DataFrame(
        {
            "Open": close + rng.normal(0, 0.5, n_days),
            "High": close + abs(rng.normal(0, 1, n_days)),
            "Low": close - abs(rng.normal(0, 1, n_days)),
            "Close": close,
            "Volume": rng.integers(1_000_000, 10_000_000, n_days).astype(float),
            "AdjClose": close,
        },
        index=dates,
    )


def _make_intraday_df(n_days: int = 10, bars_per_day: int = 78, seed: int = 42) -> pd.DataFrame:
    """テスト用5分足DataFrame (tz-aware, ET)。"""
    rng = np.random.default_rng(seed)
    import pytz

    et = pytz.timezone("America/New_York")
    timestamps = []
    for d in pd.bdate_range("2024-01-02", periods=n_days, freq="B"):
        base = pd.Timestamp(d.year, d.month, d.day, 9, 30, tz=et)
        for i in range(bars_per_day):
            timestamps.append(base + pd.Timedelta(minutes=5 * i))

    n = len(timestamps)
    close = 50.0 + np.cumsum(rng.normal(0, 0.2, n))
    return pd.DataFrame(
        {
            "Open": close + rng.normal(0, 0.1, n),
            "High": close + abs(rng.normal(0, 0.2, n)),
            "Low": close - abs(rng.normal(0, 0.2, n)),
            "Close": close,
            "Volume": rng.integers(10_000, 500_000, n).astype(float),
            "VWAP": close + rng.normal(0, 0.05, n),
            "NumTrades": rng.integers(100, 5_000, n),
        },
        index=pd.DatetimeIndex(timestamps),
    )


def _make_macro_df(name: str, n_days: int = 100, seed: int = 42) -> pd.DataFrame:
    """テスト用マクロDataFrame。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=n_days, freq="B")
    base = {"VIX": 20.0, "VIX3M": 22.0, "HY_SPREAD": 3.5, "BRENT": 75.0,
            "YIELD_CURVE": 0.5, "USD_INDEX": 104.0, "US10Y": 4.3}.get(name, 50.0)
    values = base + np.cumsum(rng.normal(0, 0.5, n_days))
    return pd.DataFrame({"value": values}, index=dates)


# ══════════════════════════════════════════════════════════════════════
# 1. 定数・マッピングのテスト
# ══════════════════════════════════════════════════════════════════════


class TestConstants:
    """定数とマッピングの妥当性。"""

    def test_symbols_daily_count(self):
        from src.signal_runner import SYMBOLS_DAILY
        assert len(SYMBOLS_DAILY) == 10

    def test_symbols_intraday_count(self):
        from src.signal_runner import SYMBOLS_INTRADAY
        assert len(SYMBOLS_INTRADAY) == 18

    def test_bear_pair_map_covers_bull_symbols(self):
        """Bull銘柄に対してBearペアが定義されている。"""
        from src.signal_runner import BEAR_PAIR_MAP
        expected_bulls = {"SOXL", "TQQQ", "TECL", "SPXL", "TNA"}
        for bull in expected_bulls:
            assert bull in BEAR_PAIR_MAP, f"{bull} のBearペアが未定義"

    def test_refutation_tests_for_each_bias_type(self):
        """ADR-013 L136-146: bias_test_typeごとの反証テスト判定マッピング。"""
        from src.signal_runner import REFUTATION_JUDGE_MAP
        assert set(REFUTATION_JUDGE_MAP.keys()) == {
            "unconditional", "regime_conditional", "structural", "direction_fixed",
        }
        # unconditional と structural は4つ全て
        assert set(REFUTATION_JUDGE_MAP["unconditional"]) == {
            "shuffle", "random_data", "reverse_direction", "period_exclusion",
        }
        assert set(REFUTATION_JUDGE_MAP["structural"]) == {
            "shuffle", "random_data", "reverse_direction", "period_exclusion",
        }
        # regime_conditional: シャッフル + ランダム対照 + 逆方向
        assert set(REFUTATION_JUDGE_MAP["regime_conditional"]) == {
            "shuffle", "random_data", "reverse_direction",
        }
        # direction_fixed: シャッフル + ランダム対照 + 期間除外
        assert set(REFUTATION_JUDGE_MAP["direction_fixed"]) == {
            "shuffle", "random_data", "period_exclusion",
        }


# ══════════════════════════════════════════════════════════════════════
# 2. データ準備のテスト
# ══════════════════════════════════════════════════════════════════════


class TestLoadMacro:
    """マクロデータ読み込みとマージ。"""

    def test_load_single_macro(self, tmp_path):
        """単一マクロ系列を日足indexにマージ。"""
        from src.signal_runner import merge_macro

        daily_df = _make_daily_df(100)
        macro_df = _make_macro_df("VIX", 50)
        macro_df.to_parquet(tmp_path / "VIX.parquet")

        result = merge_macro(daily_df, ["VIX"], macro_dir=tmp_path)
        assert "vix" in result.columns
        # マクロ範囲外はNaN
        assert result["vix"].isna().any()
        # マクロ範囲内は値がある
        assert result["vix"].notna().any()

    def test_load_multiple_macro(self, tmp_path):
        """複数マクロ系列をマージ。"""
        from src.signal_runner import merge_macro

        daily_df = _make_daily_df(100)
        for name in ["VIX", "VIX3M"]:
            macro_df = _make_macro_df(name, 100)
            macro_df.to_parquet(tmp_path / f"{name}.parquet")

        result = merge_macro(daily_df, ["VIX", "VIX3M"], macro_dir=tmp_path)
        assert "vix" in result.columns
        assert "vix3m" in result.columns

    def test_empty_macro_list(self):
        """requires_macro=[]のとき何も変更しない。"""
        from src.signal_runner import merge_macro

        daily_df = _make_daily_df(50)
        result = merge_macro(daily_df, [])
        pd.testing.assert_frame_equal(result, daily_df)


class TestMergePair:
    """ペアシンボルデータのマージ。"""

    def test_merge_pair_adds_columns(self, tmp_path):
        """pair_Close, pair_Volumeが追加される。"""
        from src.signal_runner import merge_pair

        main_df = _make_daily_df(100, seed=1)
        pair_df = _make_daily_df(100, seed=2)
        pair_df.to_parquet(tmp_path / "SOXS.parquet")

        result = merge_pair(main_df, "SOXS", daily_dir=tmp_path)
        assert "pair_Close" in result.columns
        assert "pair_Volume" in result.columns

    def test_merge_pair_index_alignment(self, tmp_path):
        """ペアのindexが主シンボルと異なってもalign。"""
        from src.signal_runner import merge_pair

        main_df = _make_daily_df(100, seed=1)
        pair_df = _make_daily_df(80, seed=2)  # 短い
        pair_df.to_parquet(tmp_path / "SOXS.parquet")

        result = merge_pair(main_df, "SOXS", daily_dir=tmp_path)
        assert len(result) == len(main_df)
        assert result["pair_Close"].isna().any()  # 欠損部分はNaN


# ══════════════════════════════════════════════════════════════════════
# 3. リターン計算のテスト
# ══════════════════════════════════════════════════════════════════════


class TestComputeReturns:
    """次バーリターンの計算。"""

    def test_daily_returns_shape(self):
        """日足リターンは元データと同じ長さ。"""
        from src.signal_runner import compute_next_returns

        df = _make_daily_df(100)
        ret = compute_next_returns(df, "daily")
        assert len(ret) == len(df)

    def test_daily_returns_shifted(self):
        """日足リターンはshift(-1)で未来リターンを取得。"""
        from src.signal_runner import compute_next_returns

        df = _make_daily_df(100)
        ret = compute_next_returns(df, "daily")
        # 手計算: ret[i] = (Close[i+1] - Close[i]) / Close[i]
        expected_0 = (df["Close"].iloc[1] - df["Close"].iloc[0]) / df["Close"].iloc[0]
        assert abs(ret.iloc[0] - expected_0) < 1e-10

    def test_daily_returns_last_is_nan(self):
        """最終バーのリターンはNaN（未来がない）。"""
        from src.signal_runner import compute_next_returns

        df = _make_daily_df(50)
        ret = compute_next_returns(df, "daily")
        assert pd.isna(ret.iloc[-1])

    def test_intraday_returns(self):
        """5分足リターンも同じロジック。"""
        from src.signal_runner import compute_next_returns

        df = _make_intraday_df(5, 78)
        ret = compute_next_returns(df, "intraday")
        expected_0 = (df["Close"].iloc[1] - df["Close"].iloc[0]) / df["Close"].iloc[0]
        assert abs(ret.iloc[0] - expected_0) < 1e-10


# ══════════════════════════════════════════════════════════════════════
# 4. 仮説実行のテスト
# ══════════════════════════════════════════════════════════════════════


class TestRunHypothesis:
    """単一仮説の実行フロー。"""

    def test_returns_result_dict_with_required_keys(self):
        """結果dictがrecord_resultの必須カラムを全て含む。"""
        from src.signal_runner import run_hypothesis
        from src.research_utils import REQUIRED_COLUMNS

        df = _make_daily_df(100)
        hyp = {
            "id": "H-TEST-01",
            "func": lambda df: df["Close"].pct_change() > 0,
            "direction": "long",
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 99,
        }
        result = run_hypothesis(hyp, df, "SOXL")
        for col in REQUIRED_COLUMNS:
            assert col in result, f"必須カラム '{col}' が結果に含まれていない"

    def test_screen_signal_called(self):
        """screen_signalが呼ばれている。"""
        from src.signal_runner import run_hypothesis

        df = _make_daily_df(100)
        hyp = {
            "id": "H-TEST-02",
            "func": lambda df: df["Close"].pct_change() > 0,
            "direction": "long",
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 99,
        }
        result = run_hypothesis(hyp, df, "SOXL")
        assert "metric_value" in result
        assert "pvalue" in result

    def test_refutation_results_included(self):
        """反証テスト結果がresult dictに含まれる。"""
        from src.signal_runner import run_hypothesis

        df = _make_daily_df(200)
        hyp = {
            "id": "H-TEST-03",
            "func": lambda df: df["Close"].pct_change() > 0,
            "direction": "long",
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 99,
        }
        result = run_hypothesis(hyp, df, "SOXL")
        # 全4種の反証テスト結果が記録される（実行は全て、判定はbias_test_typeに応じて）
        assert "refute_shuffle_pvalue" in result
        assert "refute_random_data_fp_rate" in result
        assert "refute_reverse_direction_diff" in result
        assert "refute_period_exclusion_survived" in result

    def test_signal_error_recorded_not_raised(self):
        """信号関数がエラーを出してもrunnerはクラッシュしない。"""
        from src.signal_runner import run_hypothesis

        df = _make_daily_df(100)
        hyp = {
            "id": "H-TEST-ERR",
            "func": lambda df: 1 / 0,  # ZeroDivisionError
            "direction": "long",
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 99,
        }
        result = run_hypothesis(hyp, df, "SOXL")
        assert result["passed"] is False
        assert "error" in result["raw_detail"].lower()


# ══════════════════════════════════════════════════════════════════════
# 5. 不変量テスト
# ══════════════════════════════════════════════════════════════════════


class TestInvariants:
    """出力の不変量。"""

    @pytest.mark.parametrize("seed", [1, 2, 3, 4])
    def test_result_id_matches_hypothesis(self, seed):
        """結果のidは常に仮説のidと一致。"""
        from src.signal_runner import run_hypothesis

        df = _make_daily_df(100, seed=seed)
        hyp = {
            "id": f"H-INV-{seed}",
            "func": lambda df: df["Close"].pct_change() > 0,
            "direction": "long",
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 99,
        }
        result = run_hypothesis(hyp, df, "SOXL")
        assert result["id"] == hyp["id"]

    @pytest.mark.parametrize("seed", [1, 2, 3, 4])
    def test_n_samples_non_negative(self, seed):
        """n_samplesは常に0以上。"""
        from src.signal_runner import run_hypothesis

        df = _make_daily_df(50, seed=seed)
        hyp = {
            "id": f"H-INV-N-{seed}",
            "func": lambda df: df["Close"].pct_change() > 0,
            "direction": "long",
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 99,
        }
        result = run_hypothesis(hyp, df, "SOXL")
        assert result["n_samples"] >= 0

    def test_all_refutation_tests_always_executed(self):
        """bias_test_typeに関わらず、全4種の反証テストが実行される（判定だけが異なる）。"""
        from src.signal_runner import run_hypothesis

        df = _make_daily_df(200)
        for bt in ["unconditional", "regime_conditional", "structural", "direction_fixed"]:
            hyp = {
                "id": f"H-BT-{bt}",
                "func": lambda df: df["Close"].pct_change() > 0,
                "direction": "long",
                "timeframe": "daily",
                "bias_test_type": bt,
                "requires_macro": [],
                "requires_pair": False,
                "category": 99,
            }
            result = run_hypothesis(hyp, df, "SOXL")
            assert "refute_shuffle_pvalue" in result
            assert "refute_random_data_fp_rate" in result
            assert "refute_reverse_direction_diff" in result
            assert "refute_period_exclusion_survived" in result


# ══════════════════════════════════════════════════════════════════════
# 6. 境界テスト
# ══════════════════════════════════════════════════════════════════════


class TestBoundary:
    """境界条件。"""

    def test_all_nan_signal(self):
        """全NaNシグナルでもクラッシュしない。"""
        from src.signal_runner import run_hypothesis

        df = _make_daily_df(50)
        hyp = {
            "id": "H-BOUND-NAN",
            "func": lambda df: pd.Series(np.nan, index=df.index),
            "direction": "long",
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 99,
        }
        result = run_hypothesis(hyp, df, "SOXL")
        assert result["passed"] is False

    def test_constant_signal(self):
        """定数シグナル（全True）でもクラッシュしない。"""
        from src.signal_runner import run_hypothesis

        df = _make_daily_df(50)
        hyp = {
            "id": "H-BOUND-CONST",
            "func": lambda df: pd.Series(True, index=df.index),
            "direction": "long",
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 99,
        }
        result = run_hypothesis(hyp, df, "SOXL")
        assert isinstance(result["passed"], bool)

    def test_small_n_below_30(self):
        """N < 30 でscreen_signalが不合格になる。"""
        from src.signal_runner import run_hypothesis

        df = _make_daily_df(20)
        hyp = {
            "id": "H-BOUND-SMALL",
            "func": lambda df: df["Close"].pct_change() > 0,
            "direction": "long",
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 99,
        }
        result = run_hypothesis(hyp, df, "SOXL")
        assert result["passed"] is False


class TestFloatSignalRefutation:
    """float信号に対する反証テスト判定除外。"""

    def test_float_signal_dtype_recorded(self):
        """float信号はsignal_dtype='float'として記録される。"""
        from src.signal_runner import run_hypothesis

        df = _make_daily_df(200)
        hyp = {
            "id": "H-FLOAT-01",
            "func": lambda df: df["Close"].pct_change(),  # float信号
            "direction": "long",
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 99,
        }
        result = run_hypothesis(hyp, df, "SOXL")
        assert result["signal_dtype"] == "float"
        # 全4種のテスト結果は記録される（実行はされている）
        assert "refute_random_data_fp_rate" in result
        assert "refute_reverse_direction_diff" in result

    def test_bool_signal_dtype_recorded(self):
        """bool信号はsignal_dtype='bool'として記録される。"""
        from src.signal_runner import run_hypothesis

        df = _make_daily_df(200)
        hyp = {
            "id": "H-BOOL-01",
            "func": lambda df: df["Close"].pct_change() > 0,  # bool信号
            "direction": "long",
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 99,
        }
        result = run_hypothesis(hyp, df, "SOXL")
        assert result["signal_dtype"] == "bool"
