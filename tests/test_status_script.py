"""scripts/status.py の純ロジックのテスト。

I/O (DuckDB / Parquet / yfinance) はテスト対象外。表示文言の不変条件だけを見る:
  - 失効時は「いつ切れたか」と「どう直すか」が同じ行に出る
  - 有効時に再認証コマンドを出さない (不要なブラウザ起動を誘発しない)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.status import format_token_status, humanize_elapsed
from src.db import JST, TokenStatus

NOW = datetime(2026, 9, 11, 18, 10, tzinfo=JST)


def _status(status, expires_at, refresh_count=21) -> TokenStatus:
    return TokenStatus(
        provider="saxo", environment="live", token_type="refresh",
        status=status, expires_at=expires_at, refresh_count=refresh_count,
    )


class TestHumanizeElapsed:
    def test_days_and_hours(self):
        assert humanize_elapsed(timedelta(days=2, hours=3, minutes=40)) == "2日3時間"

    def test_hours_and_minutes(self):
        assert humanize_elapsed(timedelta(hours=1, minutes=5)) == "1時間5分"

    def test_minutes_only(self):
        assert humanize_elapsed(timedelta(minutes=48)) == "48分"

    def test_negative_delta_is_absolute(self):
        """符号は呼び出し側の文言が持つ。ここでは大きさだけを返す。"""
        assert humanize_elapsed(timedelta(minutes=-48)) == "48分"


class TestFormatTokenStatus:
    def test_expired_shows_when_and_how_to_fix(self):
        expired_at = datetime(2026, 9, 9, 19, 5, tzinfo=JST)
        line = format_token_status(_status("expired", expired_at), now=NOW)

        assert "失効" in line
        assert "2026-09-09 19:05 JST" in line
        assert "1日23時間前" in line
        assert "scripts/saxo_oauth_init.py" in line

    def test_valid_does_not_suggest_reauth(self):
        """有効なのに再認証コマンドを出すと、不要なブラウザ起動を誘発する。"""
        line = format_token_status(
            _status("valid", NOW + timedelta(minutes=48)), now=NOW
        )

        assert "有効" in line
        assert "残り 48分" in line
        assert "saxo_oauth_init" not in line

    def test_valid_shows_refresh_count(self):
        line = format_token_status(
            _status("valid", NOW + timedelta(minutes=48)), now=NOW
        )

        assert "refresh 21回" in line

    def test_missing_asks_for_initial_auth(self):
        line = format_token_status(_status("missing", None, refresh_count=None), now=NOW)

        assert "未取得" in line
        assert "scripts/saxo_oauth_init.py" in line
