"""FRED APIクライアント（9シリーズ対応）

API制約（https://fred.stlouisfed.org/docs/api/api_key.html）:
  - 120 requests/minute
  - API key必須（無料）
  - 9シリーズ × 1リクエスト = 9回/実行。制限に対して十分余裕あり
"""
from __future__ import annotations

import os
from datetime import date
from typing import Optional

import requests

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

SERIES_CONFIG = {
    "VIX": "VIXCLS",
    "VIX3M": "VXVCLS",
    "VXN": "VXNCLS",
    "BRENT": "DCOILBRENTEU",
    "US10Y": "DGS10",
    "FEDFUNDS": "FEDFUNDS",
    "YIELD_CURVE": "T10Y2Y",
    "HY_SPREAD": "BAMLH0A0HYM2",
    "USD_INDEX": "DTWEXBGS",
}


class FredAPIError(Exception):
    pass


class FredClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    @classmethod
    def from_env(cls) -> FredClient:
        key = os.environ.get("FRED_API_KEY")
        if not key:
            raise ValueError("FRED_API_KEY environment variable not set")
        return cls(api_key=key)

    def fetch_series(
        self,
        series_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": "asc",
        }
        if start_date:
            params["observation_start"] = start_date.isoformat()
        if end_date:
            params["observation_end"] = end_date.isoformat()

        resp = requests.get(FRED_BASE_URL, params=params)
        if resp.status_code != 200:
            raise FredAPIError(f"FRED API error {resp.status_code}: {resp.text}")

        data = resp.json()
        if "error_message" in data:
            raise FredAPIError(f"FRED API error: {data['error_message']}")

        records = []
        for obs in data.get("observations", []):
            if obs["value"] == ".":
                continue
            records.append({
                "date": obs["date"],
                "value": float(obs["value"]),
            })
        return records

    def fetch_all(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict[str, list[dict]]:
        results = {}
        for name, series_id in SERIES_CONFIG.items():
            results[name] = self.fetch_series(series_id, start_date, end_date)
        return results
