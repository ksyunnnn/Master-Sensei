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


class TestSourceTracking:
    """ADR-009: Parquetにsource/updated_at列を追加"""

    def test_save_macro_with_source(self, cache):
        idx = pd.date_range("2026-03-01", periods=3, freq="B")
        df = pd.DataFrame({"value": [25.0, 26.0, 24.5]}, index=idx)
        cache.save_macro("VIX", df, source="fred")
        loaded = cache.load_macro("VIX")
        assert "source" in loaded.columns
        assert all(loaded["source"] == "fred")

    def test_save_macro_with_updated_at(self, cache):
        idx = pd.date_range("2026-03-01", periods=3, freq="B")
        df = pd.DataFrame({"value": [25.0, 26.0, 24.5]}, index=idx)
        cache.save_macro("VIX", df, source="yfinance")
        loaded = cache.load_macro("VIX")
        assert "updated_at" in loaded.columns
        assert all(loaded["updated_at"].notna())

    def test_save_daily_with_source(self, cache):
        df = _make_daily_df()
        cache.save_daily("TQQQ", df, source="tiingo")
        loaded = cache.load_daily("TQQQ")
        assert "source" in loaded.columns
        assert all(loaded["source"] == "tiingo")

    def test_source_updated_on_overwrite(self, cache):
        """上書き時にsourceが更新される"""
        idx = pd.date_range("2026-03-03", periods=3, freq="B")
        df1 = pd.DataFrame({"value": [25.0, 26.0, 24.5]}, index=idx)
        cache.save_macro("VIX", df1, source="yfinance")

        df2 = pd.DataFrame({"value": [25.1, 26.1, 24.6]}, index=idx)
        cache.save_macro("VIX", df2, source="fred")

        loaded = cache.load_macro("VIX")
        assert len(loaded) == 3
        assert all(loaded["source"] == "fred")  # keep="last"で上書き

    def test_merge_with_legacy_parquet_without_source(self, cache):
        """移行期: source列なしの既存Parquetにsource付きデータを追記"""
        idx1 = pd.date_range("2026-03-03", periods=3, freq="B")
        df_legacy = pd.DataFrame({"value": [25.0, 26.0, 24.5]}, index=idx1)
        cache.save_macro("VIX", df_legacy)  # source未指定（旧形式）

        idx2 = pd.date_range("2026-03-06", periods=2, freq="B")
        df_new = pd.DataFrame({"value": [27.0, 28.0]}, index=idx2)
        cache.save_macro("VIX", df_new, source="fred")

        loaded = cache.load_macro("VIX")
        assert len(loaded) == 5
        assert "source" in loaded.columns
        # 新しい行はsource="fred"、古い行はNone/NaN
        assert loaded.iloc[-1]["source"] == "fred"


class TestMetadata:
    def test_get_all_metadata(self, cache):
        df = _make_daily_df()
        cache.save_daily("TQQQ", df)
        meta = cache.get_all_metadata()
        assert "TQQQ" in meta["daily"]
        assert meta["daily"]["TQQQ"]["row_count"] == 5
