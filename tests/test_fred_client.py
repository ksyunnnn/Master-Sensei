"""FredClient ユニットテスト"""
from datetime import date

import pytest
import responses

from src.fred_client import FredClient, FredAPIError, FRED_BASE_URL, SERIES_CONFIG


@pytest.fixture
def client():
    return FredClient(api_key="test_key")


class TestFredClient:
    @responses.activate
    def test_fetch_series_success(self, client):
        responses.add(
            responses.GET, FRED_BASE_URL,
            json={"observations": [
                {"date": "2026-03-25", "value": "25.5"},
                {"date": "2026-03-26", "value": "26.0"},
            ]},
            status=200,
        )
        result = client.fetch_series("VIXCLS")
        assert len(result) == 2
        assert result[0]["value"] == 25.5

    @responses.activate
    def test_fetch_series_skips_missing_values(self, client):
        responses.add(
            responses.GET, FRED_BASE_URL,
            json={"observations": [
                {"date": "2026-03-25", "value": "."},
                {"date": "2026-03-26", "value": "26.0"},
            ]},
            status=200,
        )
        result = client.fetch_series("VIXCLS")
        assert len(result) == 1

    @responses.activate
    def test_fetch_series_api_error(self, client):
        responses.add(responses.GET, FRED_BASE_URL, status=500, body="Server Error")
        with pytest.raises(FredAPIError):
            client.fetch_series("VIXCLS")

    @responses.activate
    def test_fetch_series_with_date_range(self, client):
        responses.add(responses.GET, FRED_BASE_URL, json={"observations": []}, status=200)
        client.fetch_series("VIXCLS", start_date=date(2026, 3, 1), end_date=date(2026, 3, 26))
        assert "observation_start=2026-03-01" in responses.calls[0].request.url

    def test_series_config_covers_expected_series(self):
        """収集対象の系列名と FRED シリーズ ID を明示的に固定する。

        件数だけを assert すると系列を1本足すたびに落ちるうえ、
        「何が入っているべきか」がテストから読み取れない。
        """
        assert SERIES_CONFIG == {
            "VIX": "VIXCLS",
            "VIX3M": "VXVCLS",
            "VXN": "VXNCLS",
            "BRENT": "DCOILBRENTEU",
            "US10Y": "DGS10",
            "US30Y": "DGS30",
            "REAL10Y": "DFII10",
            "REAL30Y": "DFII30",
            "BREAKEVEN10Y": "T10YIE",
            "FEDFUNDS": "FEDFUNDS",
            "YIELD_CURVE": "T10Y2Y",
            "HY_SPREAD": "BAMLH0A0HYM2",
            "USD_INDEX": "DTWEXBGS",
        }
