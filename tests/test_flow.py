"""フロー評価ロジックのテスト"""
from src.flow import (
    assess_price_momentum,
    assess_vix_change,
    assess_volume_surge,
    assess_sigma_position,
    assess_flow,
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
