"""scripts/saxo_oauth_init.py ユニットテスト

CLI 全体の E2E は手動 (ブラウザ介入必要)。本ファイルは pure-function 部分
(loopback validation, idempotency guard, chmod) を対象。
"""
from __future__ import annotations

import importlib.util
import os
import stat
import sys
import threading
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def saxo_oauth_init():
    """scripts/saxo_oauth_init.py を module として import (path 経由)"""
    spec = importlib.util.spec_from_file_location(
        "saxo_oauth_init",
        Path(__file__).parent.parent / "scripts" / "saxo_oauth_init.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestValidateLoopbackHost:
    def test_localhost_ok(self, saxo_oauth_init):
        saxo_oauth_init._validate_loopback_host("localhost")

    def test_127_ok(self, saxo_oauth_init):
        saxo_oauth_init._validate_loopback_host("127.0.0.1")

    def test_ipv6_loopback_ok(self, saxo_oauth_init):
        saxo_oauth_init._validate_loopback_host("::1")

    def test_none_rejected(self, saxo_oauth_init):
        with pytest.raises(SystemExit, match="could not be parsed"):
            saxo_oauth_init._validate_loopback_host(None)

    def test_external_ip_rejected(self, saxo_oauth_init):
        with pytest.raises(SystemExit, match="must be a loopback"):
            saxo_oauth_init._validate_loopback_host("8.8.8.8")

    def test_0_0_0_0_rejected(self, saxo_oauth_init):
        with pytest.raises(SystemExit, match="must be a loopback"):
            saxo_oauth_init._validate_loopback_host("0.0.0.0")

    def test_external_hostname_rejected(self, saxo_oauth_init):
        with pytest.raises(SystemExit, match="must be 'localhost'"):
            saxo_oauth_init._validate_loopback_host("evil.example.com")


class TestEnsureDbFileMode:
    def test_chmod_sets_600(self, saxo_oauth_init, tmp_path):
        f = tmp_path / "test.duckdb"
        f.write_bytes(b"dummy")
        f.chmod(0o644)
        saxo_oauth_init._ensure_db_file_mode(f)
        mode = stat.S_IMODE(f.stat().st_mode)
        assert mode == 0o600

    def test_missing_file_no_error(self, saxo_oauth_init, tmp_path):
        """存在しない path は no-op (chmod 試行しない)"""
        f = tmp_path / "nonexistent.duckdb"
        saxo_oauth_init._ensure_db_file_mode(f)
        assert not f.exists()

    def test_idempotent_on_already_600(self, saxo_oauth_init, tmp_path):
        f = tmp_path / "test.duckdb"
        f.write_bytes(b"dummy")
        f.chmod(0o600)
        saxo_oauth_init._ensure_db_file_mode(f)
        assert stat.S_IMODE(f.stat().st_mode) == 0o600


class TestCallbackHandlerIdempotency:
    def test_second_callback_ignored_after_event_set(self, saxo_oauth_init):
        """do_GET が 2回呼ばれても result.code/error は最初の値を保持"""
        result = saxo_oauth_init._CallbackResult()
        handler_cls = saxo_oauth_init._make_handler(
            expected_state="STATE_X", result=result,
        )

        result.code = "first_code"
        result.state = "STATE_X"
        result.event.set()

        from unittest.mock import MagicMock
        fake_self = MagicMock()  # no spec so wfile/end_headers are auto-mocked
        fake_self.path = "/callback?code=second_code&state=STATE_X"

        handler_cls.do_GET(fake_self)

        assert result.code == "first_code"
        assert result.error is None

    def test_state_mismatch_does_not_leak_expected(self, saxo_oauth_init):
        """state mismatch error message に expected_state を含めない (secret 漏洩防止)"""
        result = saxo_oauth_init._CallbackResult()
        secret = "EXPECTED_SECRET_VALUE_192bit"
        handler_cls = saxo_oauth_init._make_handler(
            expected_state=secret, result=result,
        )

        from unittest.mock import MagicMock
        fake_self = MagicMock()
        fake_self.path = "/callback?code=x&state=WRONG_STATE"

        handler_cls.do_GET(fake_self)

        assert result.error is not None
        assert secret not in result.error, (
            f"expected_state ({secret}) leaked into error message: {result.error}"
        )
