"""フロー評価ロジックのテスト"""
import pandas as pd
import pytest
from src.flow import (
    assess_price_momentum,
    assess_vix_change,
    assess_volume_surge,
    assess_sigma_position,
    assess_flow,
    compute_flow_inputs,
    FlowAssessment,
)
from src.regime import IndicatorAssessment


class TestPriceMomentum:
    """1日/3日リターンによるモメンタム判定"""

    def test_strong_bullish(self):
        result = assess_price_momentum(daily_return_1d=0.10, daily_return_3d=0.15)
        assert result.score == 2
        assert result.regime == "strong_bullish"

    def test_bullish(self):
        result = assess_price_momentum(daily_return_1d=0.06, daily_return_3d=0.09)
        assert result.score == 1
        assert result.regime == "bullish"

    def test_neutral_positive(self):
        result = assess_price_momentum(daily_return_1d=0.02, daily_return_3d=0.03)
        assert result.score == 0
        assert result.regime == "neutral"

    def test_neutral_negative(self):
        result = assess_price_momentum(daily_return_1d=-0.02, daily_return_3d=-0.03)
        assert result.score == 0
        assert result.regime == "neutral"

    def test_bearish(self):
        result = assess_price_momentum(daily_return_1d=-0.06, daily_return_3d=-0.09)
        assert result.score == -1
        assert result.regime == "bearish"

    def test_strong_bearish(self):
        result = assess_price_momentum(daily_return_1d=-0.10, daily_return_3d=-0.15)
        assert result.score == -2
        assert result.regime == "strong_bearish"

    def test_1d_only(self):
        result = assess_price_momentum(daily_return_1d=0.10)
        assert result.score == 2

    def test_3d_only(self):
        result = assess_price_momentum(daily_return_3d=0.15)
        assert result.score == 2

    def test_mixed_signals_use_average(self):
        """1dと3dが矛盾する場合、加重平均で判定"""
        result = assess_price_momentum(daily_return_1d=0.10, daily_return_3d=-0.05)
        assert result.score in [0, 1]  # 混合シグナル


class TestVixChange:
    """VIX日次変化率による判定"""

    def test_sharp_drop(self):
        """VIX急落 = bullish（恐怖の急速な緩和）"""
        result = assess_vix_change(-0.15)
        assert result.score == 2
        assert result.regime == "sharp_drop"

    def test_moderate_drop(self):
        result = assess_vix_change(-0.09)
        assert result.score == 1
        assert result.regime == "dropping"

    def test_stable(self):
        result = assess_vix_change(-0.02)
        assert result.score == 0
        assert result.regime == "stable"

    def test_rising(self):
        result = assess_vix_change(0.09)
        assert result.score == -1
        assert result.regime == "rising"

    def test_spiking(self):
        result = assess_vix_change(0.15)
        assert result.score == -2
        assert result.regime == "spiking"


class TestVolumeSurge:
    """出来高/20日平均比率（方向連動型）"""

    def test_surge_bullish(self):
        """上昇+サージ = bullish conviction"""
        result = assess_volume_surge(2.0, price_direction=1)
        assert result.score == 2
        assert result.regime == "surge"

    def test_surge_bearish(self):
        """下落+サージ = bearish conviction"""
        result = assess_volume_surge(2.0, price_direction=-1)
        assert result.score == -2
        assert result.regime == "surge"

    def test_surge_no_direction(self):
        """方向不明+サージ = neutral（方向が確定しないと増幅しない）"""
        result = assess_volume_surge(2.0, price_direction=0)
        assert result.score == 0
        assert result.regime == "surge"

    def test_above_avg_bullish(self):
        result = assess_volume_surge(1.3, price_direction=1)
        assert result.score == 1

    def test_above_avg_bearish(self):
        result = assess_volume_surge(1.3, price_direction=-1)
        assert result.score == -1

    def test_normal(self):
        result = assess_volume_surge(1.0, price_direction=1)
        assert result.score == 0
        assert result.regime == "normal"

    def test_low_volume(self):
        result = assess_volume_surge(0.6, price_direction=1)
        assert result.score == 0
        assert result.regime == "low"


class TestSigmaPosition:
    """(Close-SMA20)/std20 によるポジション判定"""

    def test_extreme_high(self):
        result = assess_sigma_position(2.5)
        assert result.score == 2
        assert result.regime == "extreme_high"

    def test_above_mean(self):
        result = assess_sigma_position(1.5)
        assert result.score == 1
        assert result.regime == "above_mean"

    def test_at_mean(self):
        result = assess_sigma_position(0.3)
        assert result.score == 0
        assert result.regime == "at_mean"

    def test_below_mean(self):
        result = assess_sigma_position(-1.5)
        assert result.score == -1
        assert result.regime == "below_mean"

    def test_extreme_low(self):
        result = assess_sigma_position(-2.5)
        assert result.score == -2
        assert result.regime == "extreme_low"


class TestAssessFlow:
    """統合フロー判定"""

    def test_bullish_flow(self):
        result = assess_flow(
            symbol="SOXL",
            daily_return_1d=0.10,
            daily_return_3d=0.15,
            vix_change_1d=-0.15,
            volume_ratio=2.0,
            sigma_position=0.0,
        )
        assert isinstance(result, FlowAssessment)
        assert result.overall == "bullish"
        assert result.overall_score > 0.5
        assert result.symbol == "SOXL"

    def test_bearish_flow(self):
        """下落+出来高サージ → 出来高がbearish方向に増幅"""
        result = assess_flow(
            symbol="TQQQ",
            daily_return_1d=-0.10,
            daily_return_3d=-0.15,
            vix_change_1d=0.15,
            volume_ratio=2.0,
            sigma_position=-2.0,
        )
        assert result.overall == "bearish"
        assert result.overall_score < -0.5

    def test_neutral_flow(self):
        result = assess_flow(
            symbol="TECL",
            daily_return_1d=0.01,
            vix_change_1d=-0.01,
            volume_ratio=1.0,
            sigma_position=0.0,
        )
        assert result.overall == "neutral"

    def test_no_data(self):
        result = assess_flow(symbol="SPXL")
        assert result.overall == "unknown"
        assert result.overall_score == 0.0

    def test_partial_data(self):
        """一部指標のみでも判定可能"""
        result = assess_flow(
            symbol="SOXL",
            daily_return_1d=0.10,
            vix_change_1d=-0.15,
        )
        assert result.overall in ("bullish", "neutral", "bearish")
        assert len(result.indicators) == 2

    def test_march_31_soxl_is_bullish(self):
        """3/31 SOXL: +17.9%, VIX -18%, 出来高1.3x → bullish"""
        result = assess_flow(
            symbol="SOXL",
            daily_return_1d=0.179,
            daily_return_3d=-0.024,  # 3日で見るとまだマイナス
            vix_change_1d=-0.175,
            volume_ratio=1.3,
            sigma_position=-1.02,
        )
        assert result.overall == "bullish"
        assert result.overall_score > 0.5

    def test_indicators_use_regime_type(self):
        """IndicatorAssessmentはregime.pyと同じ型を使用"""
        result = assess_flow(
            symbol="SOXL",
            daily_return_1d=0.10,
        )
        assert len(result.indicators) == 1
        ind = result.indicators[0]
        assert isinstance(ind, IndicatorAssessment)


class TestComputeFlowInputs:
    """Parquetデータからassess_flow()の入力値を自動計算"""

    @pytest.fixture
    def daily_df(self):
        """25日分の日足データ（20日SMA/σ計算に十分な長さ）"""
        dates = pd.date_range("2026-03-01", periods=25, freq="B")
        # 緩やかな上昇トレンド + 最終日に大きな上昇
        closes = [40 + i * 0.5 for i in range(24)] + [60.0]
        volumes = [1_000_000] * 24 + [2_500_000]  # 最終日は出来高サージ
        return pd.DataFrame(
            {"Close": closes, "Volume": volumes},
            index=pd.DatetimeIndex(dates, name="Date"),
        )

    @pytest.fixture
    def vix_df(self):
        """25日分のVIXデータ"""
        dates = pd.date_range("2026-03-01", periods=25, freq="B")
        # 安定推移 + 最終日に急落
        values = [25.0] * 24 + [20.0]
        return pd.DataFrame(
            {"value": values},
            index=pd.DatetimeIndex(dates, name="Date"),
        )

    def test_returns_all_keys(self, daily_df, vix_df):
        result = compute_flow_inputs(daily_df, vix_df)
        expected_keys = {
            "daily_return_1d", "daily_return_3d",
            "vix_change_1d", "volume_ratio", "sigma_position",
        }
        assert set(result.keys()) == expected_keys

    def test_daily_return_1d(self, daily_df, vix_df):
        result = compute_flow_inputs(daily_df, vix_df)
        # 前日Close=51.5, 最終日Close=60.0 → (60-51.5)/51.5
        expected = (60.0 - 51.5) / 51.5
        assert abs(result["daily_return_1d"] - expected) < 0.001

    def test_daily_return_3d(self, daily_df, vix_df):
        result = compute_flow_inputs(daily_df, vix_df)
        # 3日前Close=50.5, 最終日Close=60.0
        expected = (60.0 - 50.5) / 50.5
        assert abs(result["daily_return_3d"] - expected) < 0.001

    def test_vix_change_1d(self, daily_df, vix_df):
        result = compute_flow_inputs(daily_df, vix_df)
        # 前日VIX=25.0, 最終日VIX=20.0 → (20-25)/25 = -0.20
        assert abs(result["vix_change_1d"] - (-0.20)) < 0.001

    def test_volume_ratio(self, daily_df, vix_df):
        result = compute_flow_inputs(daily_df, vix_df)
        # 最終日Volume=2,500,000、20日平均は全部1,000,000
        # ratio = 2,500,000 / 1,000,000 = 2.5
        assert result["volume_ratio"] > 2.0

    def test_sigma_position(self, daily_df, vix_df):
        result = compute_flow_inputs(daily_df, vix_df)
        # 最終日Close=60.0は20日SMAより大幅に上方 → 正のσ
        assert result["sigma_position"] > 1.0

    def test_insufficient_daily_data(self, vix_df):
        """日足が20日未満の場合、volume_ratioとsigma_positionはNone"""
        dates = pd.date_range("2026-03-20", periods=5, freq="B")
        short_df = pd.DataFrame(
            {"Close": [40, 41, 42, 43, 44], "Volume": [1_000_000] * 5},
            index=pd.DatetimeIndex(dates, name="Date"),
        )
        result = compute_flow_inputs(short_df, vix_df)
        assert result["daily_return_1d"] is not None  # 2日あればOK
        assert result["volume_ratio"] is None  # 20日分ないのでNone
        assert result["sigma_position"] is None

    def test_no_vix_data(self, daily_df):
        """VIXデータなしの場合、vix_change_1dはNone"""
        empty_vix = pd.DataFrame(columns=["value"])
        result = compute_flow_inputs(daily_df, empty_vix)
        assert result["vix_change_1d"] is None
        assert result["daily_return_1d"] is not None
