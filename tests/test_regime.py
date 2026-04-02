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


class TestToSaveKwargs:
    """RegimeAssessment.to_save_kwargs() のテスト

    目的: assess_regime() の結果を save_regime() にそのまま渡せる
    dict に変換する。indicator.name → DB kwargs のマッピングを
    コード内に閉じ込め、推測の余地を排除する。
    """

    def test_full_data(self):
        """全指標ありの場合、6つのregimeカラム + overall + reasoning + 6つのvalue"""
        values = {
            "VIX": 26.37, "VIX3M": 24.86, "HY_SPREAD": 3.28,
            "YIELD_CURVE": 0.52, "BRENT": 108.17, "USD_INDEX": 120.89,
        }
        r = assess_regime(
            vix=values["VIX"], vix3m=values["VIX3M"],
            hy_spread=values["HY_SPREAD"], yield_curve=values["YIELD_CURVE"],
            oil=values["BRENT"], usd=values["USD_INDEX"],
        )
        kwargs = r.to_save_kwargs(values)

        # save_regime() の全キーワード引数が揃っている
        assert kwargs["overall"] == "risk_off"
        assert kwargs["reasoning"]
        assert kwargs["vix_regime"] == "high"
        assert kwargs["vix_term_structure"] == "backwardation"
        assert kwargs["credit_regime"] == "widening"
        assert kwargs["yield_curve_regime"] == "normal"
        assert kwargs["oil_regime"] == "crisis"
        assert kwargs["dollar_regime"] == "normal"
        # 入力値スナップショット
        assert kwargs["vix_value"] == 26.37
        assert kwargs["vix3m_value"] == 24.86
        assert kwargs["hy_spread_value"] == 3.28
        assert kwargs["yield_curve_value"] == 0.52
        assert kwargs["oil_value"] == 108.17
        assert kwargs["usd_value"] == 120.89

    def test_partial_data(self):
        """一部データのみの場合、欠損指標のregimeはNone"""
        values = {"VIX": 30.0}
        r = assess_regime(vix=30.0)
        kwargs = r.to_save_kwargs(values)

        assert kwargs["overall"] == "risk_off"
        assert kwargs["vix_regime"] == "high"
        # 欠損指標はNone
        assert kwargs["vix_term_structure"] is None
        assert kwargs["credit_regime"] is None
        assert kwargs["oil_regime"] is None
        # 欠損の入力値もNone
        assert kwargs["vix3m_value"] is None
        assert kwargs["oil_value"] is None

    def test_kwargs_match_save_regime_signature(self):
        """返却されるキーが save_regime() のシグネチャと一致する"""
        import inspect
        from src.db import SenseiDB
        sig = inspect.signature(SenseiDB.save_regime)
        # dt(第1引数)とself を除いたキーワード引数
        expected_keys = {
            name for name, param in sig.parameters.items()
            if name not in ("self", "dt") and param.kind == param.KEYWORD_ONLY
        }
        values = {
            "VIX": 20.0, "VIX3M": 22.0, "HY_SPREAD": 3.0,
            "YIELD_CURVE": 0.5, "BRENT": 70.0, "USD_INDEX": 120.0,
        }
        r = assess_regime(
            vix=values["VIX"], vix3m=values["VIX3M"],
            hy_spread=values["HY_SPREAD"], yield_curve=values["YIELD_CURVE"],
            oil=values["BRENT"], usd=values["USD_INDEX"],
        )
        kwargs = r.to_save_kwargs(values)
        assert set(kwargs.keys()) == expected_keys
