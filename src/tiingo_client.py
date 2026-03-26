"""Tiingo APIクライアント（日足・5分足対応）

API制約（Free tier / https://www.tiingo.com/about/pricing）:
  - 50 requests/hour, 1,000 requests/day
  - 500 unique symbols/month
  - IEX(5分足): 2,000 data points/request（~128営業日分）
  - EOD(日足): 制限なし（全期間1リクエスト）
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
logger = logging.getLogger(__name__)

# API制約定数
RATE_LIMIT_PER_HOUR = 50
RATE_LIMIT_INTERVAL = 3600 / RATE_LIMIT_PER_HOUR  # 72秒/リクエスト（最悪ケース）
SAFE_INTERVAL = 2.0  # 通常運用: 11リクエスト/実行なので2秒で十分
IEX_MAX_DATAPOINTS = 10000  # 5分足の1リクエストあたり上限（2026-03-26実測）


@dataclass
class TiingoConfig:
    api_key: str
    base_url: str = "https://api.tiingo.com"
    timeout: int = 30

    @classmethod
    def from_env(cls) -> TiingoConfig:
        api_key = os.environ.get("TIINGO_API_KEY")
        if not api_key:
            raise ValueError("TIINGO_API_KEY environment variable is not set")
        return cls(api_key=api_key)


TRADING_SYMBOLS = ["TQQQ", "SOXL", "TECL", "SPXL", "SOXS"]
REFERENCE_SYMBOLS = ["VIXY"]
ALL_SYMBOLS = TRADING_SYMBOLS + REFERENCE_SYMBOLS


class TiingoFetcher:
    def __init__(self, config: TiingoConfig, request_interval: float = SAFE_INTERVAL):
        self.config = config
        self._request_interval = request_interval
        self._last_request_time = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Token {config.api_key}"
        })

    def _throttle(self):
        """レート制限を守るためリクエスト間隔を確保"""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._request_interval:
            wait = self._request_interval - elapsed
            logger.debug(f"Rate limit: waiting {wait:.1f}s")
            time.sleep(wait)
        self._last_request_time = time.monotonic()

    def fetch(self, symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        url = f"{self.config.base_url}/tiingo/daily/{symbol}/prices"
        params = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "format": "json",
            "resampleFreq": "daily"
        }

        self._throttle()
        resp = self._session.get(url, params=params, timeout=self.config.timeout)
        resp.raise_for_status()
        data = resp.json()

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        column_mapping = {
            "date": "Date", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume",
            "adjClose": "AdjClose",
        }
        df = df.rename(columns=column_mapping)
        df["Date"] = pd.to_datetime(df["Date"]).dt.date
        df = df.set_index("Date")
        df.index = pd.to_datetime(df.index)

        required_cols = ["Open", "High", "Low", "Close", "Volume", "AdjClose"]
        return df[[c for c in required_cols if c in df.columns]]

    def fetch_intraday(
        self, symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        resample_freq: str = "5min"
    ) -> pd.DataFrame:
        url = f"{self.config.base_url}/iex/{symbol}/prices"
        params = {"resampleFreq": resample_freq, "format": "json"}
        if start_date:
            params["startDate"] = start_date.isoformat()
        if end_date:
            params["endDate"] = end_date.isoformat()

        self._throttle()
        resp = self._session.get(url, params=params, timeout=self.config.timeout)
        resp.raise_for_status()
        data = resp.json()

        if not data:
            return pd.DataFrame()

        if len(data) >= IEX_MAX_DATAPOINTS:
            logger.warning(f"{symbol}: IEX returned {len(data)} points (limit={IEX_MAX_DATAPOINTS}). Data may be truncated.")

        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert("America/New_York")

        column_mapping = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
        df = df.rename(columns=column_mapping)
        required_cols = ["Open", "High", "Low", "Close", "Volume"]
        return df[[c for c in required_cols if c in df.columns]]
