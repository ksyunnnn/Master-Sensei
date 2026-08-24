"""プロバイダ抽象化テスト"""
from datetime import date

import pytest

from src.providers import (
    MacroProvider,
    FredAdapter,
    YFinanceAdapter,
    ProviderChain,
    FRED_SERIES,
    YFINANCE_SERIES,
)


class FakeFredClient:
    """テスト用のFredClient模擬"""
    def __init__(self, data=None):
        self._data = data or {}

    def fetch_series(self, series_id, start_date=None, end_date=None):
        return self._data.get(series_id, [])


class FakeProvider:
    """テスト用のMacroProvider実装"""
    def __init__(self, name, series_data):
        self._name = name
        self._data = series_data

    @property
    def provider_name(self):
        return self._name

    def available_series(self):
        return list(self._data.keys())

    def fetch_series(self, series, start_date, end_date):
        if series not in self._data:
            raise ValueError(f"Not available: {series}")
        data = self._data[series]
        if isinstance(data, Exception):
            raise data
        return data


class TestProtocolConformance:
    def test_fake_provider_is_macro_provider(self):
        p = FakeProvider("test", {})
        assert isinstance(p, MacroProvider)

    def test_fred_adapter_is_macro_provider(self):
        adapter = FredAdapter(FakeFredClient())
        assert isinstance(adapter, MacroProvider)


class TestFredAdapter:
    def test_available_series(self):
        adapter = FredAdapter(FakeFredClient())
        available = adapter.available_series()
        assert "VIX" in available
        assert "BRENT" in available
        assert len(available) == len(FRED_SERIES)

    def test_fetch_series(self):
        client = FakeFredClient({"VIXCLS": [{"date": "2026-03-25", "value": 25.33}]})
        adapter = FredAdapter(client)
        result = adapter.fetch_series("VIX", date(2026, 3, 25), date(2026, 3, 25))
        assert len(result) == 1
        assert result[0]["value"] == 25.33

    def test_fetch_unknown_series(self):
        adapter = FredAdapter(FakeFredClient())
        with pytest.raises(ValueError, match="not available"):
            adapter.fetch_series("UNKNOWN", date(2026, 3, 25), date(2026, 3, 25))

    def test_provider_name(self):
        adapter = FredAdapter(FakeFredClient())
        assert adapter.provider_name == "fred"


class TestProviderChain:
    def test_first_provider_succeeds(self):
        p1 = FakeProvider("fast", {"VIX": [{"date": "2026-03-26", "value": 24.5}]})
        p2 = FakeProvider("slow", {"VIX": [{"date": "2026-03-25", "value": 25.33}]})
        chain = ProviderChain([p1, p2])
        records, source = chain.fetch("VIX", date(2026, 3, 25), date(2026, 3, 26))
        assert source == "fast"
        assert records[0]["value"] == 24.5

    def test_fallback_on_failure(self):
        p1 = FakeProvider("broken", {"VIX": RuntimeError("API down")})
        p2 = FakeProvider("backup", {"VIX": [{"date": "2026-03-26", "value": 25.0}]})
        chain = ProviderChain([p1, p2])
        records, source = chain.fetch("VIX", date(2026, 3, 25), date(2026, 3, 26))
        assert source == "backup"

    def test_fallback_on_empty(self):
        p1 = FakeProvider("empty", {"VIX": []})
        p2 = FakeProvider("has_data", {"VIX": [{"date": "2026-03-26", "value": 25.0}]})
        chain = ProviderChain([p1, p2])
        records, source = chain.fetch("VIX", date(2026, 3, 25), date(2026, 3, 26))
        assert source == "has_data"

    def test_skip_provider_without_series(self):
        p1 = FakeProvider("no_vix", {"BRENT": [{"date": "2026-03-26", "value": 95.0}]})
        p2 = FakeProvider("has_vix", {"VIX": [{"date": "2026-03-26", "value": 25.0}]})
        chain = ProviderChain([p1, p2])
        records, source = chain.fetch("VIX", date(2026, 3, 25), date(2026, 3, 26))
        assert source == "has_vix"

    def test_all_fail_raises(self):
        p1 = FakeProvider("broken", {"VIX": RuntimeError("API down")})
        chain = ProviderChain([p1])
        with pytest.raises(RuntimeError, match="All providers failed"):
            chain.fetch("VIX", date(2026, 3, 25), date(2026, 3, 26))

    def test_series_not_in_any_provider(self):
        p1 = FakeProvider("p1", {"BRENT": []})
        chain = ProviderChain([p1])
        with pytest.raises(RuntimeError, match="All providers failed"):
            chain.fetch("VIX", date(2026, 3, 25), date(2026, 3, 26))

    def test_available_series_union(self):
        p1 = FakeProvider("p1", {"VIX": [], "BRENT": []})
        p2 = FakeProvider("p2", {"VIX": [], "VIX3M": []})
        chain = ProviderChain([p1, p2])
        assert chain.available_series() == {"VIX", "BRENT", "VIX3M"}


class TestUS30Y:
    """米30年債利回り(US30Y)の収集経路テスト。

    宿題 issue#26: 2026-08-17〜19 の SOXL 下落を駆動したのは30年債利回りだったが、
    この系列自体を収集しておらず regime 判定が構造的に検知できなかった。

    取得先は FRED(DGS30) 単独とする。2026-08-24 に米財務省の日次利回り曲線(30 Yr)を
    基準として 2026年の159営業日を突合した結果、FRED は 159/159 日で完全一致した一方、
    yfinance(^TYX) は完全一致ゼロ・小数第2位に丸めても 89/159 日(56%)・最大差 0.0570 で、
    週次の金利変動と同オーダーのズレがあったため。
    """

    def test_us30y_in_fred_series(self):
        assert FRED_SERIES["US30Y"] == "DGS30"

    def test_us30y_not_in_yfinance_series(self):
        """^TYX は財務省値と一致しないため取得先に含めない(回帰防止)。"""
        assert "US30Y" not in YFINANCE_SERIES

    def test_fred_adapter_exposes_us30y(self):
        adapter = FredAdapter(FakeFredClient())
        assert "US30Y" in adapter.available_series()

    def test_yfinance_adapter_does_not_expose_us30y(self):
        adapter = YFinanceAdapter()
        assert "US30Y" not in adapter.available_series()

    def test_fred_adapter_fetches_us30y_via_dgs30(self):
        client = FakeFredClient({"DGS30": [{"date": "2026-08-21", "value": 5.276}]})
        adapter = FredAdapter(client)
        result = adapter.fetch_series("US30Y", date(2026, 8, 21), date(2026, 8, 21))
        assert len(result) == 1
        assert result[0]["value"] == 5.276

    def test_chain_resolves_us30y_from_fred_only(self):
        """yfinance が US30Y を提供しない構成でも、chain は FRED から解決する。"""
        yf_like = FakeProvider("yfinance", {"VIX": [{"date": "2026-08-21", "value": 15.9}]})
        fred_like = FakeProvider("fred", {"US30Y": [{"date": "2026-08-20", "value": 5.23}]})
        chain = ProviderChain([yf_like, fred_like])
        records, source = chain.fetch("US30Y", date(2026, 8, 20), date(2026, 8, 21))
        assert source == "fred"
        assert records[0]["value"] == 5.23

    def test_us30y_available_in_chain(self):
        """update_macro は chain.available_series() 駆動なので、ここに出ないと収集されない。"""
        yf_like = FakeProvider("yfinance", {"VIX": []})
        fred_like = FakeProvider("fred", {"US30Y": []})
        chain = ProviderChain([yf_like, fred_like])
        assert "US30Y" in chain.available_series()


class TestRateDecompositionSeries:
    """金利テーマの分解系列(実質金利・期待インフレ・債券ボラ)の収集経路テスト。

    2026-08-24 の実測(SOXX 日次リターン vs 各変数の日次変化、5年 n=1289):

        30年 名目金利    r=-0.035  t=-1.24  ← 有意でない
        30年 実質金利    r=-0.093  t=-3.36
        30年 期待インフレ r=+0.090  t=+3.24  ← 符号が逆
        MOVE(債券ボラ)   r=-0.184  t=-6.72  ← 最強。半導体固有ぶんにも有意(t=-3.31)

    名目金利が効かないのは、実質金利と期待インフレが逆符号で打ち消し合うため
    (重回帰: 実質 -0.573%/10bp t=-3.30、期待インフレ +0.928%/10bp t=+3.18、
    両者の日次変化の相関 -0.022)。したがって名目単独では帰属に使えない。

    重要: これらはいずれも「同じ日の連動」であって翌日を予測しない。水準でも
    5日変化でも、トレンド除去後に無条件平均から2SE離れる帯が一つも無かった。
    レジーム判定(regime.py)の水準閾値には使わないこと([[K-074]])。
    """

    def test_real10y_maps_to_dfii10(self):
        assert FRED_SERIES["REAL10Y"] == "DFII10"

    def test_real30y_maps_to_dfii30(self):
        assert FRED_SERIES["REAL30Y"] == "DFII30"

    def test_breakeven_in_fred_series(self):
        assert FRED_SERIES["BREAKEVEN10Y"] == "T10YIE"

    def test_move_in_yfinance_series(self):
        """MOVE は債券版 VIX。FRED に無いため yfinance から取る。"""
        assert YFINANCE_SERIES["MOVE"] == "^MOVE"

    def test_move_not_in_fred_series(self):
        assert "MOVE" not in FRED_SERIES

    def test_fred_adapter_fetches_real30y_via_dfii30(self):
        client = FakeFredClient({"DFII30": [{"date": "2026-08-20", "value": 2.95}]})
        adapter = FredAdapter(client)
        result = adapter.fetch_series("REAL30Y", date(2026, 8, 20), date(2026, 8, 20))
        assert len(result) == 1
        assert result[0]["value"] == 2.95

    def test_all_rate_series_available_in_chain(self):
        """update_macro は chain.available_series() 駆動。ここに出ないと収集されない。"""
        yf_like = FakeProvider("yfinance", {"MOVE": []})
        fred_like = FakeProvider("fred", {"REAL10Y": [], "REAL30Y": [], "BREAKEVEN10Y": []})
        chain = ProviderChain([yf_like, fred_like])
        avail = chain.available_series()
        for name in ["MOVE", "REAL10Y", "REAL30Y", "BREAKEVEN10Y"]:
            assert name in avail

    def test_breakeven30y_is_derived_not_collected(self):
        """30年期待インフレは DGS30 - DFII30 で導出する。

        FRED の 30年ブレークイーブン(T30YIEM)は月次しか無く、日次の帰属に使えない
        ため、日次の名目と実質の差として計算する。収集系列には入れない。
        """
        assert "BREAKEVEN30Y" not in FRED_SERIES
        assert "BREAKEVEN30Y" not in YFINANCE_SERIES
        assert "US30Y" in FRED_SERIES and "REAL30Y" in FRED_SERIES
