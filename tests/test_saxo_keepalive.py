"""saxo_keepalive ユニットテスト (ADR-025/026)。

- plan_next: 失効までの残り時間から refresh/sleep を決める純粋関数。
- run_keepalive: ループ本体。DB セッションは tick ごとに開閉する factory 経由
  (sleep 中はロックを保持しない)。in-memory DuckDB を共有する const factory と、
  refresh を DB の token 前進で模倣するフェイク client を使う。time.sleep は no-op
  に差し替え、stop_after で停止。
- make_session_factory: tick ごとに connect→close する DB セッション factory。
  sleep 中の DuckDB ファイルロック解放(Stop hook 等との共存)が核心。
- SingleInstanceLock: 二重起動防止。
"""
from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import duckdb
import pytest

from src.db import SenseiDB, now_jst
from src.saxo_client import BASE_URL_LIVE, PROVIDER, SaxoAuthError, SaxoConfig

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


@pytest.fixture
def config():
    return SaxoConfig(
        app_key="test_key",
        app_secret="test_secret",
        auth_url="https://live.logonvalidation.net/authorize",
        token_url="https://live.logonvalidation.net/token",
        redirect_uri="http://localhost:8080/callback",
        environment="live",
        base_url=BASE_URL_LIVE,
    )


def _save_refresh(db, *, seconds_until_expiry):
    db.save_token(
        provider=PROVIDER,
        environment="live",
        token_type="refresh",
        token_value="rt",
        expires_at=now_jst() + timedelta(seconds=seconds_until_expiry),
    )


def _const_factory(client, db):
    """毎 tick 同じ in-memory client/db を渡す factory(実接続は開閉しない)。"""
    @contextmanager
    def factory(read_only: bool = False):
        yield client, db
    return factory


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
    status = ka.run_keepalive(_const_factory(client, db), "live", sleep_fn=lambda s: None)
    assert status == "needs_reauth"
    assert client.calls == 0  # API は叩かない


def test_run_keepalive_refreshes_when_due(db):
    _save_refresh(db, seconds_until_expiry=10)  # margin 300 未満 → 即 refresh
    client = _RollingFakeClient(db)
    slept = []
    status = ka.run_keepalive(
        _const_factory(client, db), "live", margin_sec=300, sleep_fn=slept.append, stop_after=1,
    )
    assert status == "stopped"
    assert client.calls == 1  # 1回だけ roll
    assert slept  # roll 後に短い sleep が入る


def test_run_keepalive_sleeps_when_not_due_without_refresh(db):
    _save_refresh(db, seconds_until_expiry=3600)  # 余裕あり
    client = _RollingFakeClient(db)
    slept = []
    status = ka.run_keepalive(
        _const_factory(client, db), "live", margin_sec=300, max_sleep_sec=300,
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
        _const_factory(client, db), "live", margin_sec=300, retry_sleep_sec=42,
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

    status = ka.run_keepalive(_const_factory(_NoopClient(), db), "live", margin_sec=300,
                              sleep_fn=lambda s: None, stop_after=3)
    assert status == "refresh_no_progress"


# ── ロック解放(本修正の核心) ──

def test_run_keepalive_holds_no_session_during_sleep(db):
    """sleep 中は DB セッションを保持しない=ファイルロックを解放している。

    旧設計は接続をループ全寿命で保持し、sleep 中も排他ロックを掴んだままだった
    (Stop hook の read_only 接続を弾く)。本テストは sleep 時点の open 深さが 0 で
    あることを検証する。
    """
    _save_refresh(db, seconds_until_expiry=3600)  # action=sleep
    client = _RollingFakeClient(db)
    depth = {"n": 0, "max_during_sleep": 0}

    @contextmanager
    def factory(read_only: bool = False):
        depth["n"] += 1
        try:
            yield client, db
        finally:
            depth["n"] -= 1

    def sleep_fn(_):
        depth["max_during_sleep"] = max(depth["max_during_sleep"], depth["n"])

    status = ka.run_keepalive(
        factory, "live", margin_sec=300, max_sleep_sec=300,
        sleep_fn=sleep_fn, stop_after=1,
    )
    assert status == "stopped"
    assert depth["max_during_sleep"] == 0  # sleep 中はロック非保持


def test_run_keepalive_sleep_tick_opens_read_only_only(db):
    """refresh 不要な tick は read_only(共有ロック)の poll だけ。書き込みロックを取らない。"""
    _save_refresh(db, seconds_until_expiry=3600)
    client = _RollingFakeClient(db)
    modes = []

    @contextmanager
    def factory(read_only: bool = False):
        modes.append(read_only)
        yield client, db

    ka.run_keepalive(factory, "live", margin_sec=300, max_sleep_sec=300,
                     sleep_fn=lambda s: None, stop_after=1)
    assert modes == [True]  # poll(read_only)1回のみ、write 接続なし


def test_run_keepalive_refresh_tick_polls_read_only_then_writes(db):
    """refresh する tick は poll=read_only → refresh=read-write の順。排他は roll 時のみ。"""
    _save_refresh(db, seconds_until_expiry=10)  # refresh due
    client = _RollingFakeClient(db)
    modes = []

    @contextmanager
    def factory(read_only: bool = False):
        modes.append(read_only)
        yield client, db

    ka.run_keepalive(factory, "live", margin_sec=300,
                     sleep_fn=lambda s: None, stop_after=1)
    assert modes[0] is True   # poll = read_only(共有)
    assert False in modes     # refresh = read-write(排他)


# ── make_session_factory(実ファイル接続の開閉) ──

def test_make_session_factory_releases_lock_after_close(tmp_path, config):
    """factory を抜けたら接続が閉じ、別接続が read_only で開ける(ロック解放)。"""
    db_path = tmp_path / "s.duckdb"
    factory = ka.make_session_factory(db_path, config)

    with factory(read_only=False) as (client, dbx):
        assert client is not None
        dbx.save_token(
            provider=PROVIDER, environment="live", token_type="refresh",
            token_value="rt", expires_at=now_jst() + timedelta(seconds=100),
        )

    # close 後: 別プロセス相当の read_only 接続が成功する(排他ロックが残っていない)
    other = duckdb.connect(str(db_path), read_only=True)
    try:
        row = SenseiDB(other, init_schema=False).get_active_token(PROVIDER, "live", "refresh")
    finally:
        other.close()
    assert row is not None
    assert row["token_value"] == "rt"


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


# ── spawn_wake_blocker / wake_assertion (issue #22: macOS Deep Idle スリープ対策) ──
#
# 2026-09-04 23:45:41 に `Entering Sleep state due to 'Idle Sleep'` が発生し、
# 00:17 に予定していた roll が発火せず 00:51 まで遅延、その間に refresh token が
# 00:22 で失効して keepalive が needs_reauth で落ちた(pmset -g log で実測)。
# 直前の 23:45:36 に powerd が PreventUserIdleSystemSleep を Released している
# (ディスプレイが切れて sleep 抑止が外れた)。
# 対策は caffeinate -i で idle system sleep を自前で抑止すること。

class _FakePopen:
    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        self.terminated = False
        self.waited = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True
        return 0

    def poll(self):
        return None


def test_wake_blocker_uses_caffeinate_idle_flag_on_macos():
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append(argv)
        return _FakePopen(argv, **kwargs)

    proc = ka.spawn_wake_blocker(pid=4242, platform="darwin", popen=fake_popen)

    assert proc is not None
    # -i = idle system sleep の抑止。Released されたのは PreventUserIdleSystemSleep なので
    # -s(AC 時のみ)ではなく -i でなければ塞げない。
    # -w <pid> = 親が死んだら caffeinate も終了(孤児プロセスを残さない)。
    assert calls == [["caffeinate", "-i", "-w", "4242"]]


def test_wake_blocker_skips_on_non_macos():
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append(argv)
        return _FakePopen(argv, **kwargs)

    proc = ka.spawn_wake_blocker(pid=1, platform="linux", popen=fake_popen)

    assert proc is None
    assert calls == []


def test_wake_blocker_returns_none_when_caffeinate_missing():
    def fake_popen(argv, **kwargs):
        raise FileNotFoundError("caffeinate")

    # caffeinate が無くても keepalive 本体は動き続けるべき(抑止なしで劣化動作)
    assert ka.spawn_wake_blocker(pid=1, platform="darwin", popen=fake_popen) is None


def test_wake_blocker_returns_none_on_os_error():
    def fake_popen(argv, **kwargs):
        raise OSError("boom")

    assert ka.spawn_wake_blocker(pid=1, platform="darwin", popen=fake_popen) is None


def test_wake_assertion_terminates_child_on_exit():
    created = []

    def fake_popen(argv, **kwargs):
        p = _FakePopen(argv, **kwargs)
        created.append(p)
        return p

    with ka.wake_assertion(pid=7, platform="darwin", popen=fake_popen) as proc:
        assert proc is not None
        assert not proc.terminated

    assert created[0].terminated is True
    assert created[0].waited is True


def test_wake_assertion_is_noop_without_child():
    # 非 macOS では child を作らず、context manager は素通りする
    with ka.wake_assertion(pid=7, platform="linux", popen=None) as proc:
        assert proc is None
