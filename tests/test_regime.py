"""レジーム判定ロジック ユニットテスト"""
from src.regime import (
    assess_vix, assess_vix_term_structure, assess_hy_spread,
    assess_yield_curve, assess_oil, assess_dollar, assess_regime,
)


class TestVIX:
    def test_low(self):
        r = assess_vix(13.5)
        assert r.regime == "low"
        assert r.score == 2

    def test_normal(self):
        r = assess_vix(17.0)
        assert r.regime == "normal"
        assert r.score == 1

    def test_elevated(self):
        r = assess_vix(22.0)
        assert r.regime == "elevated"
        assert r.score == -1

    def test_high(self):
        r = assess_vix(28.0)
        assert r.regime == "high"
        assert r.score == -2

    def test_extreme(self):
        r = assess_vix(40.0)
        assert r.regime == "extreme"
        assert r.score == -2


class TestVIXTermStructure:
    def test_steep_contango(self):
        r = assess_vix_term_structure(0.80)
        assert r.regime == "steep_contango"
        assert r.score == 2

    def test_normal_contango(self):
        r = assess_vix_term_structure(0.90)
        assert r.regime == "contango"
        assert r.score == 1

    def test_flat(self):
        r = assess_vix_term_structure(0.97)
        assert r.regime == "flat"
        assert r.score == 0

    def test_backwardation(self):
        r = assess_vix_term_structure(1.05)
        assert r.regime == "backwardation"
        assert r.score == -2


class TestHYSpread:
    def test_tight(self):
        r = assess_hy_spread(2.5)
        assert r.regime == "tight"
        assert r.score == 2

    def test_normal(self):
        r = assess_hy_spread(3.0)
        assert r.regime == "normal"
        assert r.score == 1

    def test_widening(self):
        r = assess_hy_spread(3.3)
        assert r.regime == "widening"
        assert r.score == -1

    def test_stressed(self):
        r = assess_hy_spread(4.0)
        assert r.regime == "stressed"
        assert r.score == -2


class TestYieldCurve:
    def test_inverted(self):
        r = assess_yield_curve(-0.5)
        assert r.regime == "inverted"
        assert r.score == -2

    def test_flat(self):
        r = assess_yield_curve(0.2)
        assert r.regime == "flat"
        assert r.score == -1

    def test_normal(self):
        r = assess_yield_curve(0.5)
        assert r.regime == "normal"
        assert r.score == 1

    def test_steep(self):
        r = assess_yield_curve(0.8)
        assert r.regime == "steep"
        assert r.score == 2


class TestOil:
    def test_normal(self):
        r = assess_oil(65.0)
        assert r.regime == "normal"
        assert r.score == 1

    def test_elevated(self):
        r = assess_oil(78.0)
        assert r.regime == "elevated"
        assert r.score == 0

    def test_high(self):
        r = assess_oil(92.0)
        assert r.regime == "high"
        assert r.score == -1

    def test_crisis(self):
        r = assess_oil(105.0)
        assert r.regime == "crisis"
        assert r.score == -2


class TestDollar:
    def test_weak(self):
        r = assess_dollar(117.0)
        assert r.regime == "weak"
        assert r.score == 1

    def test_normal(self):
        r = assess_dollar(120.0)
        assert r.regime == "normal"
        assert r.score == 0

    def test_strong(self):
        r = assess_dollar(124.0)
        assert r.regime == "strong"
        assert r.score == -1


class TestRegimeIntegration:
    def test_risk_on(self):
        """低VIX + コンタンゴ + タイトスプレッド → risk_on"""
        r = assess_regime(vix=14.0, vix3m=17.0, hy_spread=2.6, yield_curve=0.5, oil=65.0, usd=120.0)
        assert r.overall == "risk_on"
        assert r.overall_score > 0.5

    def test_risk_off(self):
        """高VIX + バックワーデーション + ストレス → risk_off"""
        r = assess_regime(vix=30.0, vix3m=27.0, hy_spread=4.0, yield_curve=0.2, oil=105.0, usd=124.0)
        assert r.overall == "risk_off"
        assert r.overall_score < -0.5

    def test_neutral(self):
        """混合シグナル → neutral"""
        r = assess_regime(vix=22.0, vix3m=23.0, hy_spread=3.0, yield_curve=0.5, oil=90.0, usd=120.0)
        assert r.overall == "neutral"

    def test_partial_data(self):
        """一部データのみでも判定可能"""
        r = assess_regime(vix=30.0)
        assert r.overall == "risk_off"
        assert len(r.indicators) == 1

    def test_no_data(self):
        r = assess_regime()
        assert r.overall == "unknown"

    def test_current_market(self):
        """2026-03-24の実際の値でテスト"""
        r = assess_regime(
            vix=26.95, vix3m=26.56,
            hy_spread=3.19, yield_curve=0.49,
            oil=103.79, usd=120.28,
        )
        assert r.overall == "risk_off"
        # VIX high(-2), term backwardation(-2), HY normal(1),
        # YC normal(1), oil crisis(-2), USD normal(0)
        assert len(r.indicators) == 6
        assert r.reasoning  # 根拠テキストが生成されている

    def test_reasoning_contains_all_indicators(self):
        r = assess_regime(vix=20.0, hy_spread=3.0)
        assert "VIX" in r.reasoning
        assert "HY" in r.reasoning
