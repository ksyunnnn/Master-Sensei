"""stage2_filter.py のテスト

4層構造: 既知解・境界・不変量・統合
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_stage1_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """テスト用Stage 1結果DataFrame。"""
    rng = np.random.default_rng(seed)
    ids = [f"H-TEST-{i:03d}" for i in range(n // 2)] * 2
    return pd.DataFrame({
        "id": ids[:n],
        "symbols_tested": ["SOXL"] * (n // 2) + ["TQQQ"] * (n - n // 2),
        "refute_shuffle_pvalue": rng.uniform(0, 1, n),
        "passed_v2": rng.random(n) > 0.7,
        "direction": ["long"] * n,
        "bias_test_type": ["unconditional"] * n,
        "signal_dtype": ["float"] * n,
        "n_samples": [200] * n,
        "metric_name": ["spearman_r"] * n,
        "metric_value": rng.uniform(-0.1, 0.1, n),
    })


# ══════════════════════════════════════════════════════════════════════
# 1. VIXレジーム関数
# ══════════════════════════════════════════════════════════════════════


class TestComputeVixRegimes:
    """VIX百分位レジーム分類。"""

    def test_three_labels_returned(self):
        """3レジーム（low/mid/high）が返される。"""
        from src.stage2_filter import compute_vix_regimes

        vix = pd.Series(np.arange(1, 101, dtype=float))  # 1-100
        regimes = compute_vix_regimes(vix)
        assert set(regimes.unique()) == {"low", "mid", "high"}

    def test_33_67_split_default(self):
        """デフォルト33%/67%境界。"""
        from src.stage2_filter import compute_vix_regimes

        vix = pd.Series(np.arange(1, 101, dtype=float))
        regimes = compute_vix_regimes(vix)
        # 33パーセンタイル=33.67, 67パーセンタイル=67.33
        assert regimes.iloc[0] == "low"  # v=1
        assert regimes.iloc[50] == "mid"  # v=51
        assert regimes.iloc[99] == "high"  # v=100

    def test_custom_percentiles(self):
        """カスタム百分位。"""
        from src.stage2_filter import compute_vix_regimes

        vix = pd.Series(np.arange(1, 101, dtype=float))
        regimes = compute_vix_regimes(vix, low_percentile=20, high_percentile=80)
        # 20パーセンタイル=20.8, 80パーセンタイル=80.2
        assert regimes.iloc[5] == "low"  # v=6
        assert regimes.iloc[50] == "mid"  # v=51
        assert regimes.iloc[90] == "high"  # v=91

    def test_nan_returns_none(self):
        """NaN値はNoneラベル。"""
        from src.stage2_filter import compute_vix_regimes

        vix = pd.Series([10.0, np.nan, 30.0, 50.0])
        regimes = compute_vix_regimes(vix)
        assert regimes.iloc[1] is None

    def test_empty_series(self):
        """空Seriesは空Series返却。"""
        from src.stage2_filter import compute_vix_regimes

        regimes = compute_vix_regimes(pd.Series([], dtype=float))
        assert len(regimes) == 0

    def test_all_same_value(self):
        """全同値でもクラッシュしない。"""
        from src.stage2_filter import compute_vix_regimes

        vix = pd.Series([20.0] * 10)
        regimes = compute_vix_regimes(vix)
        # 全同値の場合、閾値も20なので全て"low"（<=20.0）扱いでよい
        assert len(regimes) == 10


# ══════════════════════════════════════════════════════════════════════
# 2. Filter 1: BH補正
# ══════════════════════════════════════════════════════════════════════


class TestFilter1BH:
    """Filter 1: BH法補正。"""

    def test_all_large_pvalues_none_pass(self):
        """全p=1は全て不合格。"""
        from src.stage2_filter import apply_filter1_bh

        pv = pd.Series([0.9, 0.95, 1.0])
        result = apply_filter1_bh(pv, alpha=0.20)
        assert not result.any()

    def test_all_small_pvalues_all_pass(self):
        """全p=0.001は全て合格。"""
        from src.stage2_filter import apply_filter1_bh

        pv = pd.Series([0.001, 0.001, 0.001])
        result = apply_filter1_bh(pv, alpha=0.20)
        assert result.all()

    def test_nan_pvalues_fail(self):
        """NaN p値は不合格扱い。"""
        from src.stage2_filter import apply_filter1_bh

        pv = pd.Series([np.nan, 0.001, np.nan])
        result = apply_filter1_bh(pv, alpha=0.20)
        assert result.iloc[0] == False
        assert result.iloc[2] == False

    def test_returns_bool_series_same_length(self):
        """入力と同じ長さのbool Series。"""
        from src.stage2_filter import apply_filter1_bh

        pv = pd.Series([0.01, 0.5, 0.001, np.nan, 0.99])
        result = apply_filter1_bh(pv, alpha=0.20)
        assert len(result) == len(pv)
        assert result.dtype == bool


# ══════════════════════════════════════════════════════════════════════
# 3. Filter 4: 複数銘柄再現
# ══════════════════════════════════════════════════════════════════════


class TestFilter4MultiSymbol:
    """Filter 4: 複数銘柄再現。"""

    def test_single_symbol_fails(self):
        """1銘柄のみは不合格。"""
        from src.stage2_filter import apply_filter4_multi_symbol

        df = pd.DataFrame({
            "id": ["H-A", "H-B"],
            "symbols_tested": ["SOXL", "TQQQ"],
            "passed_v2": [True, True],
        })
        result = apply_filter4_multi_symbol(df, min_symbols=2)
        assert not result["filter4_multi_symbol"].any()

    def test_two_symbols_pass(self):
        """2銘柄は合格。"""
        from src.stage2_filter import apply_filter4_multi_symbol

        df = pd.DataFrame({
            "id": ["H-A", "H-A", "H-B"],
            "symbols_tested": ["SOXL", "TQQQ", "SOXL"],
            "passed_v2": [True, True, True],
        })
        result = apply_filter4_multi_symbol(df, min_symbols=2)
        assert result[result["id"] == "H-A"]["filter4_multi_symbol"].all()
        assert not result[result["id"] == "H-B"]["filter4_multi_symbol"].any()

    def test_failed_rows_not_counted(self):
        """passed_v2=Falseの行はカウントしない。"""
        from src.stage2_filter import apply_filter4_multi_symbol

        df = pd.DataFrame({
            "id": ["H-A", "H-A", "H-A"],
            "symbols_tested": ["SOXL", "TQQQ", "TECL"],
            "passed_v2": [True, False, False],  # 通過は1件のみ
        })
        result = apply_filter4_multi_symbol(df, min_symbols=2)
        assert not result["filter4_multi_symbol"].any()

    def test_higher_min_symbols(self):
        """min_symbols=3で3銘柄必要。"""
        from src.stage2_filter import apply_filter4_multi_symbol

        df = pd.DataFrame({
            "id": ["H-A", "H-A", "H-A", "H-B", "H-B"],
            "symbols_tested": ["S1", "S2", "S3", "S1", "S2"],
            "passed_v2": [True] * 5,
        })
        result = apply_filter4_multi_symbol(df, min_symbols=3)
        assert result[result["id"] == "H-A"]["filter4_multi_symbol"].all()
        assert not result[result["id"] == "H-B"]["filter4_multi_symbol"].any()


# ══════════════════════════════════════════════════════════════════════
# 4. 不変量テスト
# ══════════════════════════════════════════════════════════════════════


class TestInvariants:
    """出力の不変量。"""

    @pytest.mark.parametrize("seed", [1, 2, 3, 4])
    def test_filter1_output_length(self, seed):
        """Filter 1の出力長は入力と一致。"""
        from src.stage2_filter import apply_filter1_bh

        rng = np.random.default_rng(seed)
        pv = pd.Series(rng.uniform(0, 1, 50))
        result = apply_filter1_bh(pv, alpha=0.20)
        assert len(result) == len(pv)

    @pytest.mark.parametrize("min_sym", [2, 3, 5])
    def test_filter4_pass_rate_monotonic(self, min_sym):
        """min_symbolsが増えると通過数は単調非増加。"""
        from src.stage2_filter import apply_filter4_multi_symbol

        df = pd.DataFrame({
            "id": ["H-A"] * 4 + ["H-B"] * 2 + ["H-C"] * 1,
            "symbols_tested": [f"S{i}" for i in range(7)],
            "passed_v2": [True] * 7,
        })
        result = apply_filter4_multi_symbol(df, min_symbols=min_sym)
        expected = {2: 6, 3: 4, 5: 0}
        assert result["filter4_multi_symbol"].sum() == expected[min_sym]

    def test_compute_vix_regimes_monotonic_thresholds(self):
        """low_percentile < high_percentile を前提とした単調性。"""
        from src.stage2_filter import compute_vix_regimes

        vix = pd.Series(np.linspace(10, 40, 100))
        regimes = compute_vix_regimes(vix)
        # low < mid < high のVIX順序を確認
        low_max = vix[regimes == "low"].max()
        mid_min = vix[regimes == "mid"].min()
        mid_max = vix[regimes == "mid"].max()
        high_min = vix[regimes == "high"].min()
        assert low_max <= mid_min
        assert mid_max <= high_min
