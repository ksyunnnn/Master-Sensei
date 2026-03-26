"""共有テストフィクスチャ"""
import pytest
import duckdb


@pytest.fixture
def db_conn():
    """インメモリDuckDB接続"""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()
