"""saxo_keepalive ユニットテスト (ADR-025/026)。

- plan_next: 失効までの残り時間から refresh/sleep を決める純粋関数。
- run_keepalive: ループ本体。DB は in-memory DuckDB、client はフェイク(refresh を
  DB の token 前進で模倣)。time.sleep は no-op に差し替え、stop_after で停止。
- SingleInstanceLock: 二重起動防止。
"""
from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest

from src.db import SenseiDB, now_jst
from src.saxo_client import PROVIDER, SaxoAuthError

# scripts/ は package ではないので明示ロード
_SPEC = importlib.util.spec_from_file_location(
    "saxo_keepalive",
    Path(__file__).parent.parent / "scripts" / "saxo_keepalive.py",
)
ka = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ka)


# ── plan_next (純粋関数) ──

def test_plan_next_refresh_due_when_within_margin():
    now = now_jst()
    # 残り 250s ≤ margin 300 → refresh
    action, sleep_for = ka.plan_next(now + timedelta(seconds=250), now, 300, 300)
    assert action == "refresh"
    assert sleep_for == 0.0


def test_plan_next_refresh_due_when_exactly_at_margin():
    now = now_jst()
    action, _ = ka.plan_next(now + timedelta(seconds=300), now, 300, 300)
    assert action == "refresh"


def test_plan_next_refresh_due_when_already_expired():
    now = now_jst()
    action, _ = ka.plan_next(now - timedelta(seconds=10), now, 300, 300)
    assert action == "refresh"


def test_plan_next_sleep_partial_before_margin():
    now = now_jst()
    # 残り 400s, margin 300 → 残り-margin=100 を眠る(max 300 未満)
    action, sleep_for = ka.plan_next(now + timedelta(seconds=400), now, 300, 300)
    assert action == "sleep"
    assert sleep_for == pytest.approx(100.0, abs=1.0)


def test_plan_next_sleep_capped_at_max():
    now = now_jst()
    # 残り 3600s, margin 300 → 残り-margin=3300 だが max 300 で頭打ち
    action, sleep_for = ka.plan_next(now + timedelta(seconds=3600), now, 300, 300)
    assert action == "sleep"
    assert sleep_for == 300.0


# ── run_keepalive ──

@pytest.fixture
def db(db_conn):
    return SenseiDB(db_conn)


def _save_refresh(db, *, seconds_until_expiry):
    db.save_token(
        provider=PROVIDER,
        environment="live",
        token_type="refresh",
        token_value="rt",
        expires_at=now_jst() + timedelta(seconds=seconds_until_expiry),
    )


class _RollingFakeClient:
    """get_access_token で refresh token を遠い未来へ roll するフェイク。"""

    def __init__(self, db, *, advance_seconds=3600, raises=None):
        self.db = db
        self.advance_seconds = advance_seconds
        self.calls = 0
        self._raises = list(raises or [])

    def get_access_token(self):
        self.calls += 1
        if self._raises:
            exc = self._raises.pop(0)
            if exc is not None:
                raise exc
        # roll: 新しい refresh を遠い未来で発行
        self.db.save_token(
            provider=PROVIDER, environment="live", token_type="refresh",
            token_value="rt_new", expires_at=now_jst() + timedelta(seconds=self.advance_seconds),
        )
        return "access_new"


def test_run_keepalive_no_refresh_token_returns_needs_reauth(db):
    client = _RollingFakeClient(db)
    status = ka.run_keepalive(client, db, "live", sleep_fn=lambda s: None)
    assert status == "needs_reauth"
    assert client.calls == 0  # API は叩かない


def test_run_keepalive_refreshes_when_due(db):
    _save_refresh(db, seconds_until_expiry=10)  # margin 300 未満 → 即 refresh
    client = _RollingFakeClient(db)
    slept = []
    status = ka.run_keepalive(
        client, db, "live", margin_sec=300, sleep_fn=slept.append, stop_after=1,
    )
    assert status == "stopped"
    assert client.calls == 1  # 1回だけ roll
    assert slept  # roll 後に短い sleep が入る


def test_run_keepalive_sleeps_when_not_due_without_refresh(db):
    _save_refresh(db, seconds_until_expiry=3600)  # 余裕あり
    client = _RollingFakeClient(db)
    slept = []
    status = ka.run_keepalive(
        client, db, "live", margin_sec=300, max_sleep_sec=300,
        sleep_fn=slept.append, stop_after=1,
    )
    assert status == "stopped"
    assert client.calls == 0  # 再発行は最低限=しない
    assert slept == [300.0]  # max_sleep で頭打ち


def test_run_keepalive_transient_error_retries_not_reauth(db):
    _save_refresh(db, seconds_until_expiry=10)
    client = _RollingFakeClient(db, raises=[SaxoAuthError("HTTP 503")])
    slept = []
    status = ka.run_keepalive(
        client, db, "live", margin_sec=300, retry_sleep_sec=42,
        sleep_fn=slept.append, stop_after=1,
    )
    # 一時障害は再認証扱いにせず、retry 待ちして停止
    assert status == "stopped"
    assert client.calls == 1
    assert 42 in slept


def test_run_keepalive_no_progress_when_token_not_rolled(db):
    _save_refresh(db, seconds_until_expiry=10)

    class _NoopClient:
        calls = 0
        def get_access_token(self):
            type(self).calls += 1
            return "access"  # token を前進させない

    status = ka.run_keepalive(_NoopClient(), db, "live", margin_sec=300,
                              sleep_fn=lambda s: None, stop_after=3)
    assert status == "refresh_no_progress"


# ── SingleInstanceLock ──

def test_lock_blocks_second_instance(tmp_path):
    p = tmp_path / "ka.lock"
    lock1 = ka.SingleInstanceLock(p)
    assert lock1.acquire() is True
    lock2 = ka.SingleInstanceLock(p)
    assert lock2.acquire() is False  # holder(自プロセス)生存中
    lock1.release()
    assert not p.exists()


def test_lock_reacquire_after_release(tmp_path):
    p = tmp_path / "ka.lock"
    lock1 = ka.SingleInstanceLock(p)
    assert lock1.acquire() is True
    lock1.release()
    lock2 = ka.SingleInstanceLock(p)
    assert lock2.acquire() is True
    lock2.release()


def test_lock_steals_stale_lock(tmp_path):
    p = tmp_path / "ka.lock"
    p.write_text("999999")  # 存在しない PID の stale lock
    lock = ka.SingleInstanceLock(p)
    assert lock.acquire() is True  # stale を奪取
    lock.release()
