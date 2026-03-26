"""CacheManager ユニットテスト"""
from datetime import date

import pandas as pd
import pytest

from src.cache_manager import CacheManager


@pytest.fixture
def cache(tmp_path):
    return CacheManager(tmp_path / "parquet")


def _make_daily_df(start="2026-03-01", periods=5):
    idx = pd.date_range(start, periods=periods, freq="B")
    return pd.DataFrame(
        {"Open": range(periods), "High": range(periods), "Low": range(periods),
         "Close": range(periods), "Volume": [1000] * periods},
        index=idx,
    )


class TestDaily:
    def test_save_and_load(self, cache):
        df = _make_daily_df()
        cache.save_daily("TQQQ", df)
        loaded = cache.load_daily("TQQQ")
        assert len(loaded) == 5

    def test_load_nonexistent(self, cache):
        df = cache.load_daily("NONEXIST")
        assert df.empty

    def test_merge_on_save(self, cache):
        df1 = _make_daily_df("2026-03-01", 3)
        df2 = _make_daily_df("2026-03-05", 3)
        cache.save_daily("TQQQ", df1)
        cache.save_daily("TQQQ", df2)
        loaded = cache.load_daily("TQQQ")
        assert len(loaded) == 6  # 3 + 3, no overlap

    def test_coverage_full(self, cache):
        df = _make_daily_df("2026-03-01", 20)
        cache.save_daily("TQQQ", df)
        covered, _, _ = cache.get_daily_coverage("TQQQ", date(2026, 3, 3), date(2026, 3, 10))
        assert covered is True

    def test_coverage_missing(self, cache):
        covered, start, end = cache.get_daily_coverage("TQQQ", date(2026, 3, 1), date(2026, 3, 10))
        assert covered is False
        assert start == date(2026, 3, 1)


class TestMacro:
    def test_save_and_load_macro(self, cache):
        idx = pd.date_range("2026-03-01", periods=5, freq="B")
        df = pd.DataFrame({"value": [25.0, 26.0, 24.5, 27.0, 25.5]}, index=idx)
        cache.save_macro("VIX", df)
        loaded = cache.load_macro("VIX")
        assert len(loaded) == 5
        assert loaded.iloc[0]["value"] == 25.0

    def test_get_macro_metadata(self, cache):
        idx = pd.date_range("2026-03-01", periods=3, freq="B")
        df = pd.DataFrame({"value": [1.0, 2.0, 3.0]}, index=idx)
        cache.save_macro("HY_SPREAD", df)
        meta = cache.get_macro_metadata("HY_SPREAD")
        assert meta is not None
        assert meta.row_count == 3


class TestMetadata:
    def test_get_all_metadata(self, cache):
        df = _make_daily_df()
        cache.save_daily("TQQQ", df)
        meta = cache.get_all_metadata()
        assert "TQQQ" in meta["daily"]
        assert meta["daily"]["TQQQ"]["row_count"] == 5
