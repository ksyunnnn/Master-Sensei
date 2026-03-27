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
