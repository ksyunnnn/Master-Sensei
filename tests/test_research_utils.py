"""research_utils テスト

TDD: テストを先に書き、実装を後から埋める。
合成データで高速テスト。実データ非依存。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research_utils import (
    SignalTestResult,
    RefutationResult,
    load_daily,
    load_polygon_5min,
    screen_signal,
    bh_correction,
    walk_forward_test,
    regime_stability_test,
    multi_symbol_test,
    shuffle_test,
    random_data_control,
    reverse_direction_test,
    period_exclusion_test,
    record_result,
)


# ── Fixtures ──


@pytest.fixture
def daily_dir(tmp_path):
    """合成日足Parquet（スプリット調整テスト用）

    SOXL: 10日分。5日目にスプリット(2:1)をシミュレート。
    - Day 1-5: Close=100, AdjClose=50 (factor=0.5)
    - Day 6-10: Close=50, AdjClose=50 (factor=1.0)
    """
    dates = pd.date_range("2025-01-06", periods=10, freq="B")
    close = [100.0] * 5 + [50.0] * 5
    adj_close = [50.0] * 10
    df = pd.DataFrame(
        {
            "Open": close,
            "High": [c + 2 for c in close],
            "Low": [c - 2 for c in close],
            "Close": close,
            "Volume": [1000000] * 10,
            "AdjClose": adj_close,
            "source": ["test"] * 10,
            "updated_at": pd.Timestamp("2025-01-20"),
        },
        index=pd.Index(dates, name="Date"),
    )
    df.to_parquet(tmp_path / "SOXL.parquet")
    return tmp_path


@pytest.fixture
def intraday_dir(tmp_path):
    """合成5分足Parquet（レギュラーセッション + プレマーケット）

    SOXL: 2日分。1日目はスプリット前(Close=100付近)、2日目はスプリット後(Close=50付近)。
    レギュラーセッション: 09:30-15:55 ET = 78バー/日
    プレマーケット: 04:00-09:25 = 66バー追加
    """
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")

    bars = []
    # Day 1 (2025-01-06): pre-split, raw Close ~ 100
    day1_pre = pd.date_range(
        "2025-01-06 04:00", periods=66, freq="5min", tz=et
    )
    day1_reg = pd.date_range(
        "2025-01-06 09:30", periods=78, freq="5min", tz=et
    )
    for ts in day1_pre:
        bars.append(_bar(ts, base=100.0))
    for ts in day1_reg:
        bars.append(_bar(ts, base=100.0))

    # Day 2 (2025-01-07): post-split 2:1, raw Close ~ 50
    day2_pre = pd.date_range(
        "2025-01-07 04:00", periods=66, freq="5min", tz=et
    )
    day2_reg = pd.date_range(
        "2025-01-07 09:30", periods=78, freq="5min", tz=et
    )
    for ts in day2_pre:
        bars.append(_bar(ts, base=50.0))
    for ts in day2_reg:
        bars.append(_bar(ts, base=50.0))

    df = pd.DataFrame(bars)
    df = df.set_index("datetime")
    df.to_parquet(tmp_path / "SOXL_5min.parquet")
    return tmp_path


def _bar(ts, base: float) -> dict:
    """合成5分足バー生成"""
    return {
        "datetime": ts,
        "Open": base,
        "High": base + 0.5,
        "Low": base - 0.5,
        "Close": base + 0.1,
        "Volume": 10000.0,
        "VWAP": base + 0.05,
        "NumTrades": 500,
    }


@pytest.fixture
def daily_dir_with_split(tmp_path):
    """スプリット境界をまたぐ日足（Day5→Day6でClose半減、AdjClose連続）

    Day 1-5: Close=100, AdjClose=50
    Day 6-10: Close=50, AdjClose=50
    """
    dates = pd.date_range("2025-01-06", periods=10, freq="B")
    close = [100.0] * 5 + [50.0] * 5
    adj_close = [50.0] * 10
    df = pd.DataFrame(
        {
            "Open": close,
            "High": [c + 2 for c in close],
            "Low": [c - 2 for c in close],
            "Close": close,
            "Volume": [1000000] * 10,
            "AdjClose": adj_close,
            "source": ["test"] * 10,
            "updated_at": pd.Timestamp("2025-01-20"),
        },
        index=pd.Index(dates, name="Date"),
    )
    df.to_parquet(tmp_path / "SOXL.parquet")
    return tmp_path


@pytest.fixture
def intraday_dir_with_split(tmp_path, daily_dir_with_split):
    """スプリット前後の5分足 + 対応する日足ディレクトリパス"""
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")

    bars = []
    # Day 5 (2025-01-10 Fri): pre-split, raw Close ~ 100
    for ts in pd.date_range("2025-01-10 09:30", periods=78, freq="5min", tz=et):
        bars.append(_bar(ts, base=100.0))
    # Day 6 (2025-01-13 Mon): post-split, raw Close ~ 50
    for ts in pd.date_range("2025-01-13 09:30", periods=78, freq="5min", tz=et):
        bars.append(_bar(ts, base=50.0))

    df = pd.DataFrame(bars).set_index("datetime")
    df.to_parquet(tmp_path / "SOXL_5min.parquet")
    return tmp_path, daily_dir_with_split


# ── Tests: load_daily ──


class TestLoadDaily:
    def test_loads_parquet(self, daily_dir):
        df = load_daily("SOXL", data_dir=daily_dir)
        assert len(df) == 10
        assert df.index.name == "Date"

    def test_columns_present(self, daily_dir):
        df = load_daily("SOXL", data_dir=daily_dir)
        for col in ("Open", "High", "Low", "Close", "AdjClose", "Volume"):
            assert col in df.columns

    def test_missing_symbol_raises(self, daily_dir):
        with pytest.raises(FileNotFoundError):
            load_daily("NONEXIST", data_dir=daily_dir)


# ── Tests: load_polygon_5min ──


class TestLoadPolygon5min:
    def test_loads_regular_session_only(self, intraday_dir, daily_dir):
        df = load_polygon_5min(
            "SOXL",
            data_dir=intraday_dir,
            daily_dir=daily_dir,
            session="regular",
        )
        # 2日 × 78バー = 156
        assert len(df) == 156

    def test_loads_all_sessions(self, intraday_dir, daily_dir):
        df = load_polygon_5min(
            "SOXL",
            data_dir=intraday_dir,
            daily_dir=daily_dir,
            session="all",
        )
        # 2日 × (66 pre + 78 reg) = 288
        assert len(df) == 288

    def test_split_adjustment_prices_continuous(self, intraday_dir_with_split):
        """スプリット境界で調整後価格が連続的であること"""
        intraday_path, daily_path = intraday_dir_with_split
        df = load_polygon_5min(
            "SOXL",
            data_dir=intraday_path,
            daily_dir=daily_path,
            session="regular",
        )
        # Day 5 (pre-split): raw=100, factor=0.5 → adjusted=50
        # Day 6 (post-split): raw=50, factor=1.0 → adjusted=50
        day5 = df.loc["2025-01-10"]
        day6 = df.loc["2025-01-13"]

        # 両日の調整後Closeはほぼ同じ (base * factor)
        assert abs(day5["Close"].mean() - day6["Close"].mean()) < 1.0

    def test_split_adjustment_volume(self, intraday_dir_with_split):
        """スプリット調整でVolumeも調整されること"""
        intraday_path, daily_path = intraday_dir_with_split
        df = load_polygon_5min(
            "SOXL",
            data_dir=intraday_path,
            daily_dir=daily_path,
            session="regular",
        )
        day5 = df.loc["2025-01-10"]
        day6 = df.loc["2025-01-13"]

        # Day 5: factor=0.5 → volume / 0.5 = volume * 2
        # Day 6: factor=1.0 → volume そのまま
        # 調整後はDay5のvolumeがDay6の2倍
        assert day5["Volume"].mean() == pytest.approx(
            day6["Volume"].mean() * 2, rel=0.01
        )

    def test_no_daily_file_uses_factor_one(self, intraday_dir, tmp_path):
        """日足ファイルが存在しないシンボルは係数1.0（無調整）"""
        # SPY の5分足を作成（日足ファイルなし）
        from zoneinfo import ZoneInfo

        et = ZoneInfo("America/New_York")
        bars = []
        for ts in pd.date_range("2025-01-06 09:30", periods=78, freq="5min", tz=et):
            bars.append(_bar(ts, base=500.0))
        df = pd.DataFrame(bars).set_index("datetime")
        df.to_parquet(intraday_dir / "SPY_5min.parquet")

        empty_daily_dir = tmp_path / "empty_daily"
        empty_daily_dir.mkdir()

        result = load_polygon_5min(
            "SPY",
            data_dir=intraday_dir,
            daily_dir=empty_daily_dir,
            session="regular",
        )
        # 無調整なのでCloseは元のまま
        assert result["Close"].iloc[0] == pytest.approx(500.1, rel=0.01)

    def test_missing_intraday_raises(self, tmp_path, daily_dir):
        with pytest.raises(FileNotFoundError):
            load_polygon_5min(
                "NONEXIST", data_dir=tmp_path, daily_dir=daily_dir
            )


# ── Fixtures: screen_signal用 ──


@pytest.fixture
def strong_long_data():
    """明確なロングシグナル: シグナル発火時にリターンが正"""
    rng = np.random.default_rng(42)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    # シグナル発火時: 正のリターン（平均+1%）
    # シグナル非発火時: ランダム
    signal = pd.Series([True] * 50 + [False] * 50, index=dates)
    returns = pd.Series(index=dates, dtype=float)
    returns[signal] = rng.normal(0.01, 0.005, 50)  # ほぼ全て正
    returns[~signal] = rng.normal(0.0, 0.02, 50)
    return returns, signal


@pytest.fixture
def noise_data():
    """ノイズ: シグナルとリターンに相関なし"""
    rng = np.random.default_rng(42)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    signal = pd.Series(rng.choice([True, False], n), index=dates)
    returns = pd.Series(rng.normal(0.0, 0.02, n), index=dates)
    return returns, signal


# ── Tests: screen_signal ──


class TestScreenSignal:
    def test_strong_signal_passes(self, strong_long_data):
        returns, signal = strong_long_data
        result = screen_signal(returns, signal, "long")
        assert result.passed is True
        assert result.n_samples == 50  # シグナル発火数
        assert result.metric_value > 0.50

    def test_noise_signal_structure(self, noise_data):
        """ノイズシグナルでも出力構造が正しいこと"""
        returns, signal = noise_data
        result = screen_signal(returns, signal, "long")
        assert result.n_samples > 0
        assert result.metric_name == "direction_agreement"
        assert 0.0 <= result.metric_value <= 1.0
        assert result.pvalue is not None

    def test_insufficient_samples_fails(self):
        """N < 30 は自動不合格"""
        dates = pd.date_range("2024-01-01", periods=20, freq="B")
        returns = pd.Series(np.random.default_rng(42).normal(0, 0.01, 20), index=dates)
        signal = pd.Series([True] * 20, index=dates)
        result = screen_signal(returns, signal, "long")
        assert result.passed is False
        assert "N=20" in result.raw_detail or result.n_samples == 20

    def test_float_signal_uses_correlation(self):
        """float型シグナルはSpearman相関を使う"""
        rng = np.random.default_rng(42)
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        # シグナル値が大きいほどリターンが正
        signal = pd.Series(rng.uniform(0, 1, n), index=dates)
        returns = signal * 0.02 + pd.Series(
            rng.normal(0, 0.005, n), index=dates
        )
        result = screen_signal(returns, signal, "long")
        assert result.metric_name == "spearman_r"
        assert result.passed is True
        assert result.metric_value > 0

    def test_direction_short(self, strong_long_data):
        """ロングシグナルをshort方向で評価すると不合格"""
        returns, signal = strong_long_data
        result = screen_signal(returns, signal, "short")
        assert result.passed is False

    def test_boundary_just_above_50(self):
        """一致率51% → passed（閾値 > 50%）"""
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        # 51正 + 49負 → 一致率 51/100 = 0.51 > 0.50
        returns = pd.Series([0.01] * 51 + [-0.01] * 49, index=dates)
        signal = pd.Series([True] * n, index=dates)
        result = screen_signal(returns, signal, "long")
        assert result.passed is True
        assert result.metric_value == pytest.approx(0.51)

    def test_boundary_exactly_50(self):
        """一致率50% → failed（閾値は > 50% であって >= ではない）"""
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        returns = pd.Series([0.01] * 50 + [-0.01] * 50, index=dates)
        signal = pd.Series([True] * n, index=dates)
        result = screen_signal(returns, signal, "long")
        assert result.passed is False
        assert result.metric_value == pytest.approx(0.50)

    def test_boundary_n_exactly_30(self):
        """N=30 はギリギリ合格ライン（N >= 30）"""
        dates = pd.date_range("2024-01-01", periods=60, freq="B")
        returns = pd.Series([0.01] * 60, index=dates)
        signal = pd.Series([True] * 30 + [False] * 30, index=dates)
        result = screen_signal(returns, signal, "long")
        assert result.n_samples == 30
        assert result.passed is True  # N=30 >= 30, 一致率100%


# ── Tests: bh_correction ──


class TestBHCorrection:
    def test_all_significant(self):
        pvalues = [0.001, 0.005, 0.01]
        result = bh_correction(pvalues, alpha=0.20)
        assert all(result)

    def test_none_significant(self):
        pvalues = [0.90, 0.95, 0.99]
        result = bh_correction(pvalues, alpha=0.20)
        assert not any(result)

    def test_partial_correction(self):
        """一部だけ生き残る"""
        pvalues = [0.01, 0.05, 0.10, 0.50, 0.90]
        result = bh_correction(pvalues, alpha=0.20)
        # BH: sorted=[0.01, 0.05, 0.10, 0.50, 0.90]
        # thresholds=[0.04, 0.08, 0.12, 0.16, 0.20]
        # 0.01<0.04 ✓, 0.05<0.08 ✓, 0.10<0.12 ✓, 0.50>0.16 ✗
        assert len(result) == 5
        assert result[0] == True  # p=0.01
        assert result[1] == True  # p=0.05
        assert result[2] == True  # p=0.10
        assert result[3] == False  # p=0.50
        assert result[4] == False  # p=0.90

    def test_preserves_order(self):
        """入力順序に対応した出力"""
        pvalues = [0.50, 0.01, 0.90]
        result = bh_correction(pvalues, alpha=0.20)
        assert result[1] == True  # p=0.01（2番目）
        assert result[0] == False  # p=0.50（1番目）

    def test_boundary_p_equals_threshold(self):
        """p値がBH閾値とちょうど等しい場合 → 棄却（<=）"""
        # m=5, alpha=0.20 → thresholds=[0.04, 0.08, 0.12, 0.16, 0.20]
        # p=0.12 は rank=3 の threshold=0.12 にちょうど等しい
        pvalues = [0.01, 0.05, 0.12, 0.50, 0.90]
        result = bh_correction(pvalues, alpha=0.20)
        assert result[2] == True  # p=0.12 == threshold → 棄却

    def test_boundary_single_pvalue(self):
        """p値1つだけ → threshold=alpha"""
        result = bh_correction([0.15], alpha=0.20)
        assert result[0] == True  # 0.15 < 0.20
        result2 = bh_correction([0.25], alpha=0.20)
        assert result2[0] == False  # 0.25 > 0.20

    def test_boundary_empty_input(self):
        result = bh_correction([], alpha=0.20)
        assert len(result) == 0


# ── Tests: walk_forward_test ──


class TestWalkForwardTest:
    def test_consistent_signal_passes(self):
        """前半・後半ともにシグナルが有効なら合格"""
        rng = np.random.default_rng(42)
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        # 全期間にわたってシグナル発火、正リターン
        signal = pd.Series([True] * n, index=dates)
        returns = pd.Series(rng.normal(0.01, 0.005, n), index=dates)
        result = walk_forward_test(returns, signal, "long", n_splits=2)
        assert result.passed is True

    def test_inconsistent_oos_fails(self):
        """前半はロング有効、後半はロング無効（逆方向）→ 不合格"""
        rng = np.random.default_rng(99)
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        # 前半50: 正リターン、後半50: 負リターン
        returns = pd.Series(
            np.concatenate([
                rng.normal(0.01, 0.005, 50),
                rng.normal(-0.01, 0.005, 50),
            ]),
            index=dates,
        )
        result = walk_forward_test(returns, signal, "long", n_splits=2)
        assert result.passed is False

    def test_n_splits_default_is_two(self):
        rng = np.random.default_rng(42)
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        returns = pd.Series(rng.normal(0.01, 0.005, n), index=dates)
        result = walk_forward_test(returns, signal, "long")
        assert "2 splits" in result.raw_detail or "2分割" in result.raw_detail

    def test_boundary_odd_sample_count(self):
        """奇数サンプル(201) を2分割 → 100 + 101 で非対称。動作確認"""
        n = 201
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        returns = pd.Series([0.01] * n, index=dates)
        result = walk_forward_test(returns, signal, "long", n_splits=2)
        assert result.passed is True
        assert result.n_samples == 201

    def test_boundary_segment_too_small(self):
        """分割でセグメントサイズ < 30 → 不合格"""
        n = 50
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        returns = pd.Series([0.01] * n, index=dates)
        # 3分割 → 16〜17バー/セグメント < 30
        result = walk_forward_test(returns, signal, "long", n_splits=3)
        assert result.passed is False


# ── Tests: regime_stability_test ──


class TestRegimeStabilityTest:
    def test_stable_across_regimes_passes(self):
        """2レジーム以上でシグナルが有効なら合格"""
        rng = np.random.default_rng(42)
        n = 120
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        returns = pd.Series(rng.normal(0.01, 0.005, n), index=dates)
        regimes = pd.Series(
            ["risk_on"] * 40 + ["neutral"] * 40 + ["risk_off"] * 40,
            index=dates,
        )
        result = regime_stability_test(returns, signal, "long", regimes)
        assert result.passed is True

    def test_single_regime_only_fails(self):
        """1レジームでしか有効でないなら不合格"""
        rng = np.random.default_rng(42)
        n = 120
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        # risk_on: 正リターン、他: ランダム（負バイアス）
        returns = pd.Series(index=dates, dtype=float)
        returns.iloc[:40] = rng.normal(0.01, 0.005, 40)
        returns.iloc[40:80] = rng.normal(-0.01, 0.005, 40)
        returns.iloc[80:] = rng.normal(-0.01, 0.005, 40)
        regimes = pd.Series(
            ["risk_on"] * 40 + ["neutral"] * 40 + ["risk_off"] * 40,
            index=dates,
        )
        result = regime_stability_test(returns, signal, "long", regimes)
        assert result.passed is False

    def test_skips_small_regime_groups(self):
        """N<30のレジームグループはスキップ"""
        rng = np.random.default_rng(42)
        n = 80
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        returns = pd.Series(rng.normal(0.01, 0.005, n), index=dates)
        # risk_on=40, risk_off=40 → 両方N>=30
        # tiny=10 → スキップ → N=80-10=70 → 2レジーム有効
        regimes = pd.Series(
            ["risk_on"] * 35 + ["risk_off"] * 35 + ["tiny"] * 10,
            index=dates,
        )
        result = regime_stability_test(returns, signal, "long", regimes)
        assert result.passed is True

    def test_boundary_all_regimes_too_small(self):
        """全レジームが N<30 → テスト不能 → 不合格"""
        n = 60
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        returns = pd.Series([0.01] * n, index=dates)
        # 3レジーム各20 → 全て N<30 → 全スキップ
        regimes = pd.Series(["a"] * 20 + ["b"] * 20 + ["c"] * 20, index=dates)
        result = regime_stability_test(returns, signal, "long", regimes)
        assert result.passed is False


# ── Tests: multi_symbol_test ──


class TestMultiSymbolTest:
    def test_two_symbols_pass(self):
        result = multi_symbol_test({
            "SOXL": SignalTestResult(True, 50, "direction_agreement", 0.65, 0.01, ""),
            "TQQQ": SignalTestResult(True, 50, "direction_agreement", 0.60, 0.05, ""),
        })
        assert result.passed is True

    def test_one_symbol_only_fails(self):
        result = multi_symbol_test({
            "SOXL": SignalTestResult(True, 50, "direction_agreement", 0.65, 0.01, ""),
            "TQQQ": SignalTestResult(False, 50, "direction_agreement", 0.48, 0.60, ""),
        })
        assert result.passed is False

    def test_empty_input_fails(self):
        result = multi_symbol_test({})
        assert result.passed is False


# ── Tests: shuffle_test ──


class TestShuffleTest:
    def test_real_signal_survives_shuffle(self):
        """選択的シグナルが正リターンと相関 → シャッフルで反証されない"""
        rng = np.random.default_rng(42)
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        returns = pd.Series(rng.normal(0.0, 0.02, n), index=dates)
        # シグナルは正リターンの日だけTrue（完全相関）
        signal = pd.Series(returns > 0, index=dates)
        result = shuffle_test(returns, signal, "long", n_perms=500, rng_seed=42)
        assert result.passed is True
        assert result.test_name == "shuffle"

    def test_noise_fails_shuffle(self):
        """ノイズシグナルはシャッフルで反証される"""
        rng = np.random.default_rng(42)
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series(rng.choice([True, False], n), index=dates)
        returns = pd.Series(rng.normal(0.0, 0.02, n), index=dates)
        result = shuffle_test(returns, signal, "long", n_perms=500, rng_seed=42)
        assert result.passed is False

    def test_reproducible_with_seed(self):
        """同じseedで同じ結果"""
        rng = np.random.default_rng(42)
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        returns = pd.Series(rng.normal(0.0, 0.02, n), index=dates)
        signal = pd.Series(returns > 0, index=dates)
        r1 = shuffle_test(returns, signal, "long", n_perms=100, rng_seed=99)
        r2 = shuffle_test(returns, signal, "long", n_perms=100, rng_seed=99)
        assert r1.pvalue == r2.pvalue


# ── Tests: random_data_control ──


class TestRandomDataControl:
    def test_random_data_control_structure(self):
        """random_data_controlの出力構造が正しいこと"""
        rng = np.random.default_rng(42)
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True, False] * 100, index=dates)
        result = random_data_control(signal, "long", n_sims=200, rng_seed=42)
        assert result.test_name == "random_data"
        assert 0.0 <= result.metric_value <= 1.0  # FP率は[0,1]
        assert result.pvalue is None  # この関数はp値を返さない

    def test_always_true_signal_high_fp_rate(self):
        """全日True + ランダムリターンでも50%は方向が合うので偽陽性率が高い"""
        rng = np.random.default_rng(42)
        n = 50
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        result = random_data_control(signal, "long", n_sims=200, rng_seed=42)
        # 全True信号 + ランダムリターン(mean=0) → 期待一致率50%
        # screen_signal閾値は>50%なので、偽陽性率の期待値は約50%
        # 閾値0.3は期待値の下限として保守的（二項分布 B(200,0.5) の P(X>=60)≒0.5）
        assert result.metric_value > 0.3


# ── Tests: reverse_direction_test ──


class TestReverseDirectionTest:
    def test_asymmetric_signal_passes(self):
        """一方向のみ有効 → 非対称 → 反証されない"""
        rng = np.random.default_rng(42)
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        returns = pd.Series(rng.normal(0.01, 0.005, n), index=dates)
        result = reverse_direction_test(returns, signal)
        assert result.passed is True
        assert result.test_name == "reverse_direction"

    def test_symmetric_signal_fails(self):
        """両方向で同等 → 対称 → 反証される"""
        rng = np.random.default_rng(42)
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        returns = pd.Series(rng.normal(0.0, 0.02, n), index=dates)
        result = reverse_direction_test(returns, signal)
        assert result.passed is False


# ── Tests: period_exclusion_test ──


class TestPeriodExclusionTest:
    def test_robust_signal_survives(self):
        """広くシグナルが効いていれば、一部除外しても生き残る"""
        rng = np.random.default_rng(42)
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        returns = pd.Series(rng.normal(0.01, 0.005, n), index=dates)
        result = period_exclusion_test(returns, signal, "long")
        assert result.passed is True
        assert result.test_name == "period_exclusion"

    def test_fragile_signal_fails(self):
        """少数の極端リターンに依存するシグナルは除外で消失"""
        rng = np.random.default_rng(42)
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series([True] * n, index=dates)
        # 90バーは明確に負リターン、上位10バーだけ大きな正で平均を押し上げ
        returns = pd.Series(rng.normal(-0.005, 0.002, n), index=dates)
        returns.iloc[:10] = 0.10  # 上位10バーが巨大リターン
        result = period_exclusion_test(returns, signal, "long", exclude_fractions=[0.1])
        assert result.passed is False


# ── Tests: record_result ──

REQUIRED_COLUMNS = [
    "id", "agent", "category", "hypothesis", "direction",
    "symbols_tested", "n_samples", "metric_name", "metric_value",
    "pvalue", "regime_condition", "holding_period", "source", "raw_detail",
]


class TestRecordResult:
    def test_creates_file_with_header(self, tmp_path):
        csv_path = tmp_path / "signal_ideas.csv"
        row = {col: f"val_{col}" for col in REQUIRED_COLUMNS}
        record_result(row, output_path=csv_path)
        df = pd.read_csv(csv_path)
        assert len(df) == 1
        for col in REQUIRED_COLUMNS:
            assert col in df.columns

    def test_appends_row(self, tmp_path):
        csv_path = tmp_path / "signal_ideas.csv"
        row1 = {col: f"val1_{col}" for col in REQUIRED_COLUMNS}
        row2 = {col: f"val2_{col}" for col in REQUIRED_COLUMNS}
        record_result(row1, output_path=csv_path)
        record_result(row2, output_path=csv_path)
        df = pd.read_csv(csv_path)
        assert len(df) == 2

    def test_missing_required_column_raises(self, tmp_path):
        csv_path = tmp_path / "signal_ideas.csv"
        incomplete = {"id": "test"}  # 必須カラム不足
        with pytest.raises(ValueError):
            record_result(incomplete, output_path=csv_path)

    def test_extra_columns_preserved(self, tmp_path):
        """反証テスト結果など追加カラムも保存される"""
        csv_path = tmp_path / "signal_ideas.csv"
        row = {col: f"val_{col}" for col in REQUIRED_COLUMNS}
        row["shuffle_pvalue"] = 0.01
        row["bias_test_type"] = "unconditional"
        record_result(row, output_path=csv_path)
        df = pd.read_csv(csv_path)
        assert "shuffle_pvalue" in df.columns
        assert "bias_test_type" in df.columns


# ── 不変量テスト ──


class TestInvariantsScreenSignal:
    """screen_signal の数学的不変量"""

    @pytest.mark.parametrize("seed", [0, 42, 99, 12345])
    def test_invariant_pvalue_in_range(self, seed):
        """不変量: p値は常に [0, 1]"""
        rng = np.random.default_rng(seed)
        n = 50
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series(rng.choice([True, False], n), index=dates)
        returns = pd.Series(rng.normal(0, 0.02, n), index=dates)
        result = screen_signal(returns, signal, "long")
        if result.pvalue is not None:
            assert 0.0 <= result.pvalue <= 1.0

    @pytest.mark.parametrize("seed", [0, 42, 99, 12345])
    def test_invariant_metric_in_range(self, seed):
        """不変量: 方向一致率は [0, 1]"""
        rng = np.random.default_rng(seed)
        n = 50
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        signal = pd.Series(rng.choice([True, False], n), index=dates)
        returns = pd.Series(rng.normal(0, 0.02, n), index=dates)
        result = screen_signal(returns, signal, "long")
        assert 0.0 <= result.metric_value <= 1.0

    def test_invariant_n_samples_nonneg(self):
        """不変量: n_samples >= 0"""
        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        signal = pd.Series([False] * 10, index=dates)
        returns = pd.Series([0.01] * 10, index=dates)
        result = screen_signal(returns, signal, "long")
        assert result.n_samples >= 0


class TestInvariantsBHCorrection:
    """BH補正の数学的不変量"""

    @pytest.mark.parametrize("seed", [0, 42, 99])
    def test_invariant_output_length_matches_input(self, seed):
        """不変量: 出力長 == 入力長"""
        rng = np.random.default_rng(seed)
        n = rng.integers(1, 50)
        pvalues = rng.uniform(0, 1, n).tolist()
        result = bh_correction(pvalues, alpha=0.20)
        assert len(result) == n

    def test_invariant_stricter_alpha_rejects_fewer(self):
        """不変量: alpha が小さいほど棄却数は減る（単調性）"""
        pvalues = [0.01, 0.05, 0.10, 0.15, 0.30]
        n_rejected_20 = bh_correction(pvalues, alpha=0.20).sum()
        n_rejected_10 = bh_correction(pvalues, alpha=0.10).sum()
        n_rejected_05 = bh_correction(pvalues, alpha=0.05).sum()
        assert n_rejected_20 >= n_rejected_10 >= n_rejected_05


class TestInvariantsShuffleTest:
    """shuffle_test の数学的不変量"""

    @pytest.mark.parametrize("seed", [0, 42, 99])
    def test_invariant_pvalue_in_range(self, seed):
        """不変量: p値は [1/(n_perms+1), 1] の範囲内"""
        rng = np.random.default_rng(seed)
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        returns = pd.Series(rng.normal(0, 0.02, n), index=dates)
        signal = pd.Series(rng.choice([True, False], n), index=dates)
        n_perms = 100
        result = shuffle_test(returns, signal, "long", n_perms=n_perms, rng_seed=seed)
        # Phipson & Smyth: 最小p値 = 1/(n_perms+1)
        assert result.pvalue >= 1 / (n_perms + 1)
        assert result.pvalue <= 1.0
