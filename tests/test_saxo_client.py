"""SaxoClient ユニットテスト (ADR-025)

HTTP は requests-mock ライクに pytest-mock の Mock セッションで差し替える。
DB は in-memory DuckDB (conftest.db_conn fixture)。
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
import requests

from src.db import SenseiDB, now_jst
from src.saxo_client import (
    BASE_URL_LIVE,
    BASE_URL_SIM,
    PROVIDER,
    AccountBalance,
    SaxoAuthError,
    SaxoClient,
    SaxoConfig,
)


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


@pytest.fixture
def mock_session():
    return MagicMock(spec=requests.Session)


@pytest.fixture
def client(db, config, mock_session):
    return SaxoClient(db, config=config, session=mock_session)


def _mock_response(status: int, json_body: dict = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.text = text
    resp.json.return_value = json_body or {}
    if not resp.ok:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    return resp


class TestSaxoConfig:
    def test_from_env_live(self, monkeypatch):
        monkeypatch.setenv("SAXO_ENVIRONMENT", "live")
        monkeypatch.setenv("SAXO_APP_KEY_LIVE", "k")
        monkeypatch.setenv("SAXO_APP_SECRET_LIVE", "s")
        monkeypatch.setenv("SAXO_AUTH_URL_LIVE", "https://live.logonvalidation.net/authorize")
        monkeypatch.setenv("SAXO_TOKEN_URL_LIVE", "https://live.logonvalidation.net/token")
        monkeypatch.setenv("SAXO_REDIRECT_URI", "http://localhost:8080/callback")
        cfg = SaxoConfig.from_env()
        assert cfg.environment == "live"
        assert cfg.base_url == BASE_URL_LIVE
        assert cfg.app_key == "k"

    def test_from_env_sim(self, monkeypatch):
        monkeypatch.setenv("SAXO_ENVIRONMENT", "sim")
        monkeypatch.setenv("SAXO_APP_KEY_SIM", "k")
        monkeypatch.setenv("SAXO_APP_SECRET_SIM", "s")
        monkeypatch.setenv("SAXO_AUTH_URL_SIM", "https://sim.logonvalidation.net/authorize")
        monkeypatch.setenv("SAXO_TOKEN_URL_SIM", "https://sim.logonvalidation.net/token")
        monkeypatch.setenv("SAXO_REDIRECT_URI", "http://localhost:8080/callback")
        cfg = SaxoConfig.from_env()
        assert cfg.environment == "sim"
        assert cfg.base_url == BASE_URL_SIM

    def test_from_env_invalid_environment_raises(self, monkeypatch):
        monkeypatch.setenv("SAXO_ENVIRONMENT", "wrong")
        with pytest.raises(ValueError, match="must be 'sim' or 'live'"):
            SaxoConfig.from_env()

    def test_from_env_missing_var_raises(self, monkeypatch):
        monkeypatch.setenv("SAXO_ENVIRONMENT", "live")
        monkeypatch.delenv("SAXO_APP_KEY_LIVE", raising=False)
        monkeypatch.setenv("SAXO_APP_SECRET_LIVE", "s")
        monkeypatch.setenv("SAXO_AUTH_URL_LIVE", "https://example.com/a")
        monkeypatch.setenv("SAXO_TOKEN_URL_LIVE", "https://example.com/t")
        monkeypatch.setenv("SAXO_REDIRECT_URI", "http://localhost:8080/callback")
        with pytest.raises(ValueError, match="SAXO_APP_KEY_LIVE"):
            SaxoConfig.from_env()

    def test_from_env_http_auth_url_rejected(self, monkeypatch):
        monkeypatch.setenv("SAXO_ENVIRONMENT", "live")
        monkeypatch.setenv("SAXO_APP_KEY_LIVE", "k")
        monkeypatch.setenv("SAXO_APP_SECRET_LIVE", "s")
        monkeypatch.setenv("SAXO_AUTH_URL_LIVE", "http://insecure.example/authorize")
        monkeypatch.setenv("SAXO_TOKEN_URL_LIVE", "https://example.com/token")
        monkeypatch.setenv("SAXO_REDIRECT_URI", "http://localhost:8080/callback")
        with pytest.raises(ValueError, match="must use https://"):
            SaxoConfig.from_env()

    def test_from_env_http_token_url_rejected(self, monkeypatch):
        monkeypatch.setenv("SAXO_ENVIRONMENT", "live")
        monkeypatch.setenv("SAXO_APP_KEY_LIVE", "k")
        monkeypatch.setenv("SAXO_APP_SECRET_LIVE", "s")
        monkeypatch.setenv("SAXO_AUTH_URL_LIVE", "https://example.com/a")
        monkeypatch.setenv("SAXO_TOKEN_URL_LIVE", "http://insecure.example/token")
        monkeypatch.setenv("SAXO_REDIRECT_URI", "http://localhost:8080/callback")
        with pytest.raises(ValueError, match="must use https://"):
            SaxoConfig.from_env()


class TestBuildAuthorizationUrl:
    def test_includes_required_params(self, client):
        url = client.build_authorization_url(state="rnd123")
        assert "response_type=code" in url
        assert "client_id=test_key" in url
        assert "redirect_uri=http" in url
        assert "state=rnd123" in url


class TestExchangeCodeForTokens:
    def test_persists_access_and_refresh(self, client, db, mock_session):
        mock_session.post.return_value = _mock_response(200, {
            "access_token": "AT1",
            "refresh_token": "RT1",
            "expires_in": 1200,
            "refresh_token_expires_in": 60 * 60 * 24 * 30,
        })
        client.exchange_code_for_tokens(code="callback_code")

        access = db.get_active_token(provider=PROVIDER, environment="live", token_type="access")
        refresh = db.get_active_token(provider=PROVIDER, environment="live", token_type="refresh")
        assert access["token_value"] == "AT1"
        assert refresh["token_value"] == "RT1"
        assert access["acquired_via"] == "oauth_initial"

    def test_http_error_raises_auth_error(self, client, mock_session):
        mock_session.post.return_value = _mock_response(400, text="invalid_grant")
        with pytest.raises(SaxoAuthError, match="Initial token exchange failed"):
            client.exchange_code_for_tokens(code="bad_code")

    def test_missing_refresh_token_raises(self, client, mock_session):
        """initial exchange で refresh_token が response にない場合は明示 raise"""
        mock_session.post.return_value = _mock_response(200, {
            "access_token": "AT1",
            "expires_in": 1200,
        })
        with pytest.raises(SaxoAuthError, match="did not return refresh_token"):
            client.exchange_code_for_tokens(code="callback_code")

    def test_missing_access_token_raises(self, client, mock_session):
        """access_token 欠落も明示 raise (cryptic KeyError 防止)"""
        mock_session.post.return_value = _mock_response(200, {
            "refresh_token": "RT1",
            "expires_in": 1200,
        })
        with pytest.raises(SaxoAuthError, match="missing required keys"):
            client.exchange_code_for_tokens(code="callback_code")

    def test_non_json_response_raises(self, client, mock_session):
        """非JSON 200 response も明示 raise"""
        resp = MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.text = "<html>not json</html>"
        resp.json.side_effect = ValueError("Expecting value")
        mock_session.post.return_value = resp
        with pytest.raises(SaxoAuthError, match="non-JSON response"):
            client.exchange_code_for_tokens(code="callback_code")


class TestGetAccessToken:
    def test_returns_cached_if_buffer_ok(self, client, db, mock_session):
        db.save_token(
            provider=PROVIDER, environment="live", token_type="access",
            token_value="cached_AT", expires_at=now_jst() + timedelta(seconds=600),
        )
        result = client.get_access_token()
        assert result == "cached_AT"
        mock_session.post.assert_not_called()

    def test_refreshes_when_no_access_token(self, client, db, mock_session):
        db.save_token(
            provider=PROVIDER, environment="live", token_type="refresh",
            token_value="RT_old", expires_at=now_jst() + timedelta(days=30),
        )
        mock_session.post.return_value = _mock_response(200, {
            "access_token": "AT_new",
            "refresh_token": "RT_new",
            "expires_in": 1200,
        })
        result = client.get_access_token()
        assert result == "AT_new"
        mock_session.post.assert_called_once()

    def test_refreshes_when_buffer_too_small(self, client, db, mock_session):
        db.save_token(
            provider=PROVIDER, environment="live", token_type="access",
            token_value="AT_dying", expires_at=now_jst() + timedelta(seconds=10),
        )
        db.save_token(
            provider=PROVIDER, environment="live", token_type="refresh",
            token_value="RT_x", expires_at=now_jst() + timedelta(days=30),
        )
        mock_session.post.return_value = _mock_response(200, {
            "access_token": "AT_refreshed",
            "refresh_token": "RT_new",
            "expires_in": 1200,
        })
        result = client.get_access_token()
        assert result == "AT_refreshed"

    def test_raises_when_no_refresh_token(self, client, mock_session):
        with pytest.raises(SaxoAuthError, match="No valid refresh token"):
            client.get_access_token()
        mock_session.post.assert_not_called()

    def test_refresh_failure_revokes_refresh_token(self, client, db, mock_session):
        rt_id = db.save_token(
            provider=PROVIDER, environment="live", token_type="refresh",
            token_value="RT_bad", expires_at=now_jst() + timedelta(days=30),
        )
        mock_session.post.return_value = _mock_response(401, text="invalid refresh")
        with pytest.raises(SaxoAuthError, match="Token refresh failed"):
            client.get_access_token()
        row = db.conn.execute(
            "SELECT revoke_reason FROM auth_tokens WHERE id = ?", [rt_id]
        ).fetchone()
        assert row[0] == "refresh_http_401"

    def test_refresh_5xx_does_NOT_revoke_token(self, client, db, mock_session):
        """transient 5xx で refresh token を revoke しない (lockout 防止)"""
        rt_id = db.save_token(
            provider=PROVIDER, environment="live", token_type="refresh",
            token_value="RT_alive", expires_at=now_jst() + timedelta(days=30),
        )
        mock_session.post.return_value = _mock_response(503, text="Service Unavailable")
        with pytest.raises(SaxoAuthError, match="Token refresh failed"):
            client.get_access_token()
        row = db.conn.execute(
            "SELECT revoked_at FROM auth_tokens WHERE id = ?", [rt_id]
        ).fetchone()
        assert row[0] is None, "5xx should NOT revoke refresh token"

    def test_refresh_429_does_NOT_revoke_token(self, client, db, mock_session):
        """rate limit (429) も transient、revoke しない"""
        rt_id = db.save_token(
            provider=PROVIDER, environment="live", token_type="refresh",
            token_value="RT_alive", expires_at=now_jst() + timedelta(days=30),
        )
        mock_session.post.return_value = _mock_response(429, text="Too Many Requests")
        with pytest.raises(SaxoAuthError):
            client.get_access_token()
        row = db.conn.execute(
            "SELECT revoked_at FROM auth_tokens WHERE id = ?", [rt_id]
        ).fetchone()
        assert row[0] is None

    def test_refresh_400_invalid_grant_revokes_token(self, client, db, mock_session):
        """400 invalid_grant は definitive failure、revoke する"""
        rt_id = db.save_token(
            provider=PROVIDER, environment="live", token_type="refresh",
            token_value="RT_bad", expires_at=now_jst() + timedelta(days=30),
        )
        mock_session.post.return_value = _mock_response(400, {"error": "invalid_grant"})
        with pytest.raises(SaxoAuthError):
            client.get_access_token()
        row = db.conn.execute(
            "SELECT revoke_reason FROM auth_tokens WHERE id = ?", [rt_id]
        ).fetchone()
        assert row[0] == "refresh_http_400"

    def test_refresh_400_other_error_does_NOT_revoke_token(self, client, db, mock_session):
        """400 で error が invalid_grant 以外なら revoke しない (保守的)"""
        rt_id = db.save_token(
            provider=PROVIDER, environment="live", token_type="refresh",
            token_value="RT_alive", expires_at=now_jst() + timedelta(days=30),
        )
        mock_session.post.return_value = _mock_response(400, {"error": "temporarily_unavailable"})
        with pytest.raises(SaxoAuthError):
            client.get_access_token()
        row = db.conn.execute(
            "SELECT revoked_at FROM auth_tokens WHERE id = ?", [rt_id]
        ).fetchone()
        assert row[0] is None

    def test_refresh_rotates_old_refresh_token(self, client, db, mock_session):
        rt_id = db.save_token(
            provider=PROVIDER, environment="live", token_type="refresh",
            token_value="RT_old", expires_at=now_jst() + timedelta(days=30),
        )
        mock_session.post.return_value = _mock_response(200, {
            "access_token": "AT_new",
            "refresh_token": "RT_NEW_ROTATED",
            "expires_in": 1200,
        })
        client.get_access_token()
        # 旧 refresh は revoked
        row = db.conn.execute(
            "SELECT revoke_reason FROM auth_tokens WHERE id = ?", [rt_id]
        ).fetchone()
        assert row[0] == "rotated_on_refresh"
        # 新 refresh は active
        new_refresh = db.get_active_token(
            provider=PROVIDER, environment="live", token_type="refresh"
        )
        assert new_refresh["token_value"] == "RT_NEW_ROTATED"


class TestPortfolioApi:
    def _setup_valid_access(self, db):
        db.save_token(
            provider=PROVIDER, environment="live", token_type="access",
            token_value="AT_valid", expires_at=now_jst() + timedelta(seconds=1200),
        )

    def test_get_balances_calls_correct_endpoint(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"CashBalance": 21901})
        result = client.get_balances()
        assert result == {"CashBalance": 21901}
        call_args = mock_session.get.call_args
        assert call_args[0][0].endswith("/port/v1/balances/me")
        assert call_args.kwargs["headers"]["Authorization"] == "Bearer AT_valid"

    def test_get_positions_returns_data_array(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {
            "Data": [{"PositionId": "1", "Quantity": 1}],
        })
        result = client.get_positions()
        assert result == [{"PositionId": "1", "Quantity": 1}]

    def test_401_raises_auth_error(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(401, text="unauthorized")
        with pytest.raises(SaxoAuthError, match="401 from"):
            client.get_balances()


class TestSemanticAccessors:
    """ADR-026: raw dict 露出を防ぐ意味的アクセサ"""

    @staticmethod
    def _balance_response(spending=103099.0, cash=15216.61, settled=15216.61,
                          total=103099.0, tnb=87882.39):
        return {
            "CalculationReliability": "Ok",
            "Currency": "JPY",
            "SpendingPower": spending,
            "CashAvailableForTrading": cash if cash != 15216.61 else spending,
            "CashBalance": settled,
            "TotalValue": total,
            "UnrealizedPositionsValue": 0.0,
            "TransactionsNotBooked": tnb,
            "OpenPositionsCount": 0,
            "NetPositionsCount": 1,
            "NonMarginPositionsValue": 0.0,
        }

    def _setup_valid_access(self, db):
        db.save_token(
            provider=PROVIDER, environment="live", token_type="access",
            token_value="AT_valid", expires_at=now_jst() + timedelta(seconds=1200),
        )

    def test_get_account_balance_returns_dataclass(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._balance_response())
        bal = client.get_account_balance(
            account_key="AK", client_key="CK", account_id="77800/T126816",
        )
        assert isinstance(bal, AccountBalance)
        assert bal.account_id == "77800/T126816"
        assert bal.account_key == "AK"
        assert bal.spending_power == 103099.0
        assert bal.settled_cash_balance == 15216.61
        assert bal.transactions_not_booked == 87882.39

    def test_get_account_balance_distinguishes_spending_vs_settled(
            self, client, db, mock_session):
        """T126816 ケース: spending_power と settled が大きく乖離する"""
        self._setup_valid_access(db)
        resp = self._balance_response(spending=103099.0, settled=15216.61)
        mock_session.get.return_value = _mock_response(200, resp)
        bal = client.get_account_balance(account_key="AK", client_key="CK")
        # この差を発見できれば 2026-05-26 の誤りは再発しない
        assert bal.spending_power > bal.settled_cash_balance
        assert bal.spending_power - bal.settled_cash_balance == pytest.approx(87882.39)

    def test_get_account_balance_calls_per_account_endpoint(
            self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._balance_response())
        client.get_account_balance(account_key="AK1", client_key="CK1")
        url = mock_session.get.call_args[0][0]
        assert "AccountKey=AK1" in url
        assert "ClientKey=CK1" in url

    def test_get_account_balance_missing_field_raises(self, client, db, mock_session):
        """balance response から required field が欠けたら SaxoAuthError"""
        self._setup_valid_access(db)
        # SpendingPower を意図的に省略
        incomplete = self._balance_response()
        del incomplete["SpendingPower"]
        mock_session.get.return_value = _mock_response(200, incomplete)
        with pytest.raises(SaxoAuthError, match="missing required fields"):
            client.get_account_balance(account_key="AK", client_key="CK")

    def test_get_all_account_balances_iterates_active_only(
            self, client, db, mock_session):
        self._setup_valid_access(db)

        def _side_effect(url, headers=None, timeout=None):
            if "accounts" in url:
                return _mock_response(200, {
                    "Data": [
                        {"AccountId": "77800/P120136", "AccountKey": "K1",
                         "ClientKey": "C1", "Currency": "JPY", "Active": True},
                        {"AccountId": "77800/N122798", "AccountKey": "K2",
                         "ClientKey": "C2", "Currency": "USD", "Active": False},
                        {"AccountId": "77800/T126816", "AccountKey": "K3",
                         "ClientKey": "C3", "Currency": "JPY", "Active": True},
                    ]
                })
            return _mock_response(200, self._balance_response())

        mock_session.get.side_effect = _side_effect
        results = client.get_all_account_balances()
        assert len(results) == 2  # Inactive 1つを除外
        assert {r.account_id for r in results} == {"77800/P120136", "77800/T126816"}
