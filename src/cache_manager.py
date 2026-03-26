"""Parquetキャッシュ管理（日足・5分足・マクロ指標）"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CacheMetadata:
    symbol: str
    start_date: date
    end_date: date
    last_updated: datetime
    row_count: int

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "row_count": self.row_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CacheMetadata:
        return cls(
            symbol=data["symbol"],
            start_date=date.fromisoformat(data["start_date"]),
            end_date=date.fromisoformat(data["end_date"]),
            last_updated=datetime.fromisoformat(data["last_updated"]),
            row_count=data["row_count"],
        )


class CacheManager:
    """Parquetキャッシュ管理

    構造:
        data/parquet/
        ├── daily/           # 日足: {SYMBOL}.parquet
        ├── intraday/        # 5分足: {SYMBOL}_5min.parquet
        ├── macro/           # マクロ指標: {SERIES}.parquet
        ├── metadata.json
        ├── metadata_intraday.json
        └── metadata_macro.json
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.daily_dir = cache_dir / "daily"
        self.intraday_dir = cache_dir / "intraday"
        self.macro_dir = cache_dir / "macro"

        for d in [self.daily_dir, self.intraday_dir, self.macro_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self._metadata: Dict[str, CacheMetadata] = {}
        self._metadata_intraday: Dict[str, CacheMetadata] = {}
        self._metadata_macro: Dict[str, CacheMetadata] = {}

        self._load_metadata("metadata.json", self._metadata)
        self._load_metadata("metadata_intraday.json", self._metadata_intraday)
        self._load_metadata("metadata_macro.json", self._metadata_macro)

    def _load_metadata(self, filename: str, target: dict):
        path = self.cache_dir / filename
        if path.exists():
            with open(path) as f:
                data = json.load(f)
                target.update({k: CacheMetadata.from_dict(v) for k, v in data.items()})

    def _save_metadata(self, filename: str, source: dict):
        path = self.cache_dir / filename
        with open(path, "w") as f:
            json.dump({k: v.to_dict() for k, v in source.items()}, f, indent=2)

    # ── 共通: Parquet読み書き ──

    def _save_parquet(self, path: Path, df: pd.DataFrame, symbol: str, metadata_dict: dict, metadata_file: str):
        if df.empty:
            return

        if path.exists():
            bak = path.with_suffix(".parquet.bak")
            shutil.copy2(path, bak)
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df])
            df = df[~df.index.duplicated(keep="last")]
            df = df.sort_index()

        df.to_parquet(path, engine="pyarrow")
        metadata_dict[symbol] = CacheMetadata(
            symbol=symbol,
            start_date=df.index[0].date() if hasattr(df.index[0], 'date') else df.index[0],
            end_date=df.index[-1].date() if hasattr(df.index[-1], 'date') else df.index[-1],
            last_updated=datetime.now(),
            row_count=len(df),
        )
        self._save_metadata(metadata_file, metadata_dict)

    def _load_parquet(self, path: Path, start_date: date = None, end_date: date = None) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path)
        if start_date is not None:
            df = df[df.index >= pd.Timestamp(start_date)]
        if end_date is not None:
            df = df[df.index <= pd.Timestamp(end_date)]
        return df

    def _get_coverage(self, symbol: str, meta_dict: dict, start_date: date, end_date: date) -> Tuple[bool, Optional[date], Optional[date]]:
        meta = meta_dict.get(symbol)
        if not meta:
            return (False, start_date, end_date)
        if meta.start_date <= start_date and meta.end_date >= end_date:
            return (True, None, None)
        missing_start = start_date if start_date < meta.start_date else meta.end_date + timedelta(days=1)
        missing_end = end_date
        return (False, missing_start, missing_end)

    # ── 日足 ──

    def save_daily(self, symbol: str, df: pd.DataFrame):
        path = self.daily_dir / f"{symbol}.parquet"
        self._save_parquet(path, df, symbol, self._metadata, "metadata.json")

    def load_daily(self, symbol: str, start_date: date = None, end_date: date = None) -> pd.DataFrame:
        return self._load_parquet(self.daily_dir / f"{symbol}.parquet", start_date, end_date)

    def get_daily_coverage(self, symbol: str, start_date: date, end_date: date):
        return self._get_coverage(symbol, self._metadata, start_date, end_date)

    # ── 5分足 ──

    def save_intraday(self, symbol: str, df: pd.DataFrame):
        path = self.intraday_dir / f"{symbol}_5min.parquet"
        self._save_parquet(path, df, symbol, self._metadata_intraday, "metadata_intraday.json")

    def load_intraday(self, symbol: str, start_date: date = None, end_date: date = None) -> pd.DataFrame:
        path = self.intraday_dir / f"{symbol}_5min.parquet"
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path)
        if start_date is not None:
            df = df[df.index.date >= start_date]
        if end_date is not None:
            df = df[df.index.date <= end_date]
        return df

    def get_intraday_coverage(self, symbol: str, start_date: date, end_date: date):
        return self._get_coverage(symbol, self._metadata_intraday, start_date, end_date)

    def get_intraday_metadata(self, symbol: str) -> Optional[CacheMetadata]:
        return self._metadata_intraday.get(symbol)

    # ── マクロ指標 ──

    def save_macro(self, series_name: str, df: pd.DataFrame):
        path = self.macro_dir / f"{series_name}.parquet"
        self._save_parquet(path, df, series_name, self._metadata_macro, "metadata_macro.json")

    def load_macro(self, series_name: str) -> pd.DataFrame:
        return self._load_parquet(self.macro_dir / f"{series_name}.parquet")

    def get_macro_metadata(self, series_name: str) -> Optional[CacheMetadata]:
        return self._metadata_macro.get(series_name)

    def get_all_metadata(self) -> dict:
        return {
            "daily": {k: v.to_dict() for k, v in self._metadata.items()},
            "intraday": {k: v.to_dict() for k, v in self._metadata_intraday.items()},
            "macro": {k: v.to_dict() for k, v in self._metadata_macro.items()},
        }
