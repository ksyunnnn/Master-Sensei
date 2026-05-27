"""SenseiDB auth_tokens テーブル ユニットテスト (ADR-025)"""
from datetime import datetime, timedelta

import pytest

from src.db import JST, SenseiDB, now_jst


@pytest.fixture
def db(db_conn):
    return SenseiDB(db_conn)


def _future(seconds: int) -> datetime:
    return now_jst() + timedelta(seconds=seconds)


def _past(seconds: int) -> datetime:
    return now_jst() - timedelta(seconds=seconds)


class TestAuthTokensSchema:
    def test_table_created(self, db):
        tables = db.conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_name = 'auth_tokens'"
        ).fetchall()
        assert len(tables) == 1

    def test_required_columns_present(self, db):
        cols = {
            row[0]
            for row in db.conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'auth_tokens' AND table_schema = 'main'"
            ).fetchall()
        }
        required = {
            "id", "provider", "environment", "token_type", "token_value",
            "acquired_at", "expires_at", "acquired_via", "refresh_count",
            "metadata", "revoked_at", "revoke_reason", "created_at",
        }
        assert required <= cols


class TestSaveToken:
    def test_save_returns_id(self, db):
        tid = db.save_token(
            provider="saxo",
            environment="live",
            token_type="access",
            token_value="access_xyz",
            expires_at=_future(1200),
            acquired_via="oauth_initial",
        )
        assert isinstance(tid, int)
        assert tid >= 1

    def test_save_persists_all_fields(self, db):
        expires = _future(1200)
        tid = db.save_token(
            provider="saxo",
            environment="live",
            token_type="refresh",
            token_value="refresh_abc",
            expires_at=expires,
            acquired_via="oauth_initial",
            refresh_count=3,
            metadata='{"scope":"read"}',
        )
        row = db.conn.execute(
            "SELECT provider, environment, token_type, token_value, "
            "acquired_via, refresh_count, metadata "
            "FROM auth_tokens WHERE id = ?",
            [tid],
        ).fetchone()
        assert row == ("saxo", "live", "refresh", "refresh_abc",
                       "oauth_initial", 3, '{"scope":"read"}')

    def test_save_records_acquired_at_as_now(self, db):
        before = now_jst()
        tid = db.save_token(
            provider="saxo", environment="live", token_type="access",
            token_value="x", expires_at=_future(1200),
        )
        after = now_jst()
        acquired_at = db.conn.execute(
            "SELECT acquired_at FROM auth_tokens WHERE id = ?", [tid]
        ).fetchone()[0]
        assert before <= acquired_at <= after

    def test_save_naive_expires_at_raises(self, db):
        with pytest.raises(ValueError, match="timezone-aware"):
            db.save_token(
                provider="saxo", environment="live", token_type="access",
                token_value="x",
                expires_at=datetime(2030, 1, 1, 0, 0),
            )

    def test_save_multiple_tokens_different_ids(self, db):
        t1 = db.save_token(
            provider="saxo", environment="live", token_type="access",
            token_value="a", expires_at=_future(1200),
        )
        t2 = db.save_token(
            provider="saxo", environment="live", token_type="access",
            token_value="b", expires_at=_future(1200),
        )
        assert t1 != t2


class TestGetActiveToken:
    def test_returns_none_when_no_tokens(self, db):
        result = db.get_active_token(provider="saxo", environment="live", token_type="access")
        assert result is None

    def test_returns_latest_unexpired_unrevoked(self, db):
        db.save_token(provider="saxo", environment="live", token_type="access",
                      token_value="older", expires_at=_future(1200))
        db.save_token(provider="saxo", environment="live", token_type="access",
                      token_value="newer", expires_at=_future(1200))
        result = db.get_active_token(provider="saxo", environment="live", token_type="access")
        assert result is not None
        assert result["token_value"] == "newer"

    def test_excludes_expired(self, db):
        db.save_token(provider="saxo", environment="live", token_type="access",
                      token_value="expired", expires_at=_past(60))
        result = db.get_active_token(provider="saxo", environment="live", token_type="access")
        assert result is None

    def test_prefers_unexpired_even_if_older(self, db):
        db.save_token(provider="saxo", environment="live", token_type="access",
                      token_value="valid", expires_at=_future(1200))
        db.save_token(provider="saxo", environment="live", token_type="access",
                      token_value="expired_recent", expires_at=_past(60))
        result = db.get_active_token(provider="saxo", environment="live", token_type="access")
        assert result["token_value"] == "valid"

    def test_excludes_revoked(self, db):
        tid = db.save_token(provider="saxo", environment="live", token_type="access",
                            token_value="revoked", expires_at=_future(1200))
        db.revoke_token(tid, reason="manual_revoke")
        result = db.get_active_token(provider="saxo", environment="live", token_type="access")
        assert result is None

    def test_environment_isolation(self, db):
        db.save_token(provider="saxo", environment="sim", token_type="access",
                      token_value="sim_token", expires_at=_future(1200))
        db.save_token(provider="saxo", environment="live", token_type="access",
                      token_value="live_token", expires_at=_future(1200))
        sim_result = db.get_active_token(provider="saxo", environment="sim", token_type="access")
        live_result = db.get_active_token(provider="saxo", environment="live", token_type="access")
        assert sim_result["token_value"] == "sim_token"
        assert live_result["token_value"] == "live_token"

    def test_token_type_isolation(self, db):
        db.save_token(provider="saxo", environment="live", token_type="access",
                      token_value="access_v", expires_at=_future(1200))
        db.save_token(provider="saxo", environment="live", token_type="refresh",
                      token_value="refresh_v", expires_at=_future(60 * 60 * 24 * 60))
        access = db.get_active_token(provider="saxo", environment="live", token_type="access")
        refresh = db.get_active_token(provider="saxo", environment="live", token_type="refresh")
        assert access["token_value"] == "access_v"
        assert refresh["token_value"] == "refresh_v"


class TestRevokeToken:
    def test_revoke_sets_revoked_at_and_reason(self, db):
        tid = db.save_token(provider="saxo", environment="live", token_type="access",
                            token_value="x", expires_at=_future(1200))
        before = now_jst()
        db.revoke_token(tid, reason="oauth_refresh_failure")
        after = now_jst()
        row = db.conn.execute(
            "SELECT revoked_at, revoke_reason FROM auth_tokens WHERE id = ?",
            [tid],
        ).fetchone()
        assert row[0] is not None
        assert before <= row[0] <= after
        assert row[1] == "oauth_refresh_failure"

    def test_revoke_nonexistent_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.revoke_token(99999, reason="x")

    def test_revoke_preserves_audit_record(self, db):
        """ADR-025: append-only。revoked token は DELETE せず audit保持"""
        tid = db.save_token(provider="saxo", environment="live", token_type="access",
                            token_value="x", expires_at=_future(1200))
        db.revoke_token(tid, reason="x")
        row = db.conn.execute("SELECT id FROM auth_tokens WHERE id = ?", [tid]).fetchone()
        assert row is not None
