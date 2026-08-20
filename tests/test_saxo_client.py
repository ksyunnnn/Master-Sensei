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
    CashBooking,
    ClosedPosition,
    LivePosition,
    OpenOrder,
    SaxoAuthError,
    SaxoClient,
    SaxoConfig,
    TradeCost,
    TradeReport,
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


class TestLivePositionsAccessor:
    """ADR-026: ライブ建玉の意味的アクセサ (live↔台帳照合用)"""

    def _setup_valid_access(self, db):
        db.save_token(
            provider=PROVIDER, environment="live", token_type="access",
            token_value="AT_valid", expires_at=now_jst() + timedelta(seconds=1200),
        )

    @staticmethod
    def _position(uic=46780, amount=8.0, symbol="SOXL:arcx"):
        return {
            "PositionBase": {"AccountId": "77800/P120136", "Uic": uic,
                             "Amount": amount, "OpenPrice": 227.59},
            "PositionView": {"ProfitLossOnTradeInBaseCurrency": 2342.0},
            "DisplayAndFormat": {"Symbol": symbol},
        }

    def test_returns_semantic_dataclass(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"Data": [self._position()]})
        positions = client.get_live_positions()
        assert len(positions) == 1
        p = positions[0]
        assert isinstance(p, LivePosition)
        assert p.symbol == "SOXL"          # "SOXL:arcx" の ":" 前に正規化
        assert p.amount == 8.0
        assert p.uic == 46780

    def test_symbol_falls_back_to_uic_map(self, client, db, mock_session):
        """DisplayAndFormat.Symbol が null でも SAXO_UIC 逆引きで SOXL に解決。"""
        self._setup_valid_access(db)
        resp = {"Data": [self._position(symbol=None)]}
        mock_session.get.return_value = _mock_response(200, resp)
        positions = client.get_live_positions()
        assert positions[0].symbol == "SOXL"

    def test_unknown_uic_visible_as_placeholder(self, client, db, mock_session):
        """未知 Uic かつ symbol null → UIC:<n> で照合に可視化 (黙殺しない)。"""
        self._setup_valid_access(db)
        resp = {"Data": [self._position(uic=99999, symbol=None)]}
        mock_session.get.return_value = _mock_response(200, resp)
        positions = client.get_live_positions()
        assert positions[0].symbol == "UIC:99999"

    def test_empty_when_no_positions(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"Data": []})
        assert client.get_live_positions() == []

    def test_missing_field_raises(self, client, db, mock_session):
        self._setup_valid_access(db)
        bad = {"Data": [{"PositionBase": {"Uic": 46780, "Amount": 8.0}}]}  # AccountId/OpenPrice 欠落
        mock_session.get.return_value = _mock_response(200, bad)
        with pytest.raises(SaxoAuthError, match="missing"):
            client.get_live_positions()


class TestOpenOrdersAccessor:
    """ADR-026: ライブ未約定注文の意味的アクセサ (注文ドリフト照合用)"""

    def _setup_valid_access(self, db):
        db.save_token(
            provider=PROVIDER, environment="live", token_type="access",
            token_value="AT_valid", expires_at=now_jst() + timedelta(seconds=1200),
        )

    @staticmethod
    def _order(order_id="5409497457", price=214.0):
        return {
            "OrderId": order_id, "AccountId": "77800/P120136", "Uic": 46780,
            "Amount": 8.0, "BuySell": "Sell", "OpenOrderType": "Stop",
            "Price": price, "Status": "Working",
            "DisplayAndFormat": {"Symbol": "SOXL:arcx"},
        }

    def test_returns_semantic_dataclass(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"Data": [self._order()]})
        orders = client.get_open_orders()
        assert len(orders) == 1
        o = orders[0]
        assert isinstance(o, OpenOrder)
        assert o.order_id == "5409497457"
        assert o.symbol == "SOXL"
        assert o.buy_sell == "Sell"
        assert o.order_type == "Stop"
        assert o.price == 214.0

    def test_market_order_price_none(self, client, db, mock_session):
        self._setup_valid_access(db)
        resp = {"Data": [self._order(price=None)]}
        mock_session.get.return_value = _mock_response(200, resp)
        assert client.get_open_orders()[0].price is None

    def test_empty_when_no_orders(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"Data": []})
        assert client.get_open_orders() == []

    def test_missing_field_raises(self, client, db, mock_session):
        self._setup_valid_access(db)
        bad = {"Data": [{"OrderId": "1", "Uic": 46780}]}  # 必須多数欠落
        mock_session.get.return_value = _mock_response(200, bad)
        with pytest.raises(SaxoAuthError, match="missing"):
            client.get_open_orders()


class TestOpenOrdersRelatedLegs:
    """IFD-OCO の保護脚は親の RelatedOpenOrders[] にネストされる (issue#16)。

    トップレベルだけ走査すると stop/TP が返り値に現れず、**保護の付いていない
    建玉と誤読する**。2026-07-28 に実際に誤読しかけた。
    実測 shape は docs/api/saxo/order-fields.md を参照。
    """

    def _setup_valid_access(self, db):
        db.save_token(
            provider=PROVIDER, environment="live", token_type="access",
            token_value="AT_valid", expires_at=now_jst() + timedelta(seconds=1200),
        )

    @staticmethod
    def _master_with_legs():
        return {
            "OrderId": "5428389110", "AccountId": "77800/T126816", "Uic": 46780,
            "Amount": 8.0, "BuySell": "Buy", "OpenOrderType": "Limit",
            "Price": 95.0, "Status": "Working", "OrderRelation": "IfDoneMaster",
            "DisplayAndFormat": {"Symbol": "SOXL:arcx"},
            "RelatedOpenOrders": [
                {"OrderId": "5428389111", "OpenOrderType": "Limit",
                 "OrderPrice": 136.0, "Status": "NotWorking"},
                {"OrderId": "5428389112", "OpenOrderType": "StopIfTraded",
                 "OrderPrice": 89.0, "Status": "NotWorking"},
            ],
        }

    def test_legs_are_returned(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(
            200, {"Data": [self._master_with_legs()]})
        orders = client.get_open_orders()
        ids = [o.order_id for o in orders]
        assert ids == ["5428389110", "5428389111", "5428389112"]

    def test_leg_price_read_from_order_price(self, client, db, mock_session):
        """保護脚の価格 field は Price でなく OrderPrice。"""
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(
            200, {"Data": [self._master_with_legs()]})
        legs = {o.order_id: o for o in client.get_open_orders()}
        assert legs["5428389111"].price == 136.0
        assert legs["5428389112"].price == 89.0
        assert legs["5428389112"].order_type == "StopIfTraded"
        assert legs["5428389112"].status == "NotWorking"

    def test_leg_inherits_instrument_context_from_parent(self, client, db, mock_session):
        """脚は同一 instrument/口座の決済注文なので親から引き継ぐ (推測ではない)。"""
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(
            200, {"Data": [self._master_with_legs()]})
        legs = {o.order_id: o for o in client.get_open_orders()}
        leg = legs["5428389111"]
        assert leg.symbol == "SOXL"
        assert leg.account_id == "77800/T126816"
        assert leg.uic == 46780
        assert leg.amount == 8.0
        assert leg.parent_order_id == "5428389110"

    def test_leg_buy_sell_is_none_when_absent(self, client, db, mock_session):
        """レスポンスに BuySell が無い脚は None にする (向きを推測しない、ADR-026)。"""
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(
            200, {"Data": [self._master_with_legs()]})
        legs = {o.order_id: o for o in client.get_open_orders()}
        assert legs["5428389111"].buy_sell is None

    def test_parent_has_no_parent_order_id(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(
            200, {"Data": [self._master_with_legs()]})
        parent = client.get_open_orders()[0]
        assert parent.parent_order_id is None
        assert parent.order_relation == "IfDoneMaster"

    def test_leg_without_order_id_raises(self, client, db, mock_session):
        self._setup_valid_access(db)
        bad = self._master_with_legs()
        bad["RelatedOpenOrders"] = [{"OpenOrderType": "Limit", "OrderPrice": 1.0}]
        mock_session.get.return_value = _mock_response(200, {"Data": [bad]})
        with pytest.raises(SaxoAuthError, match="missing"):
            client.get_open_orders()


class TestClosedPositionsAccessor:
    """ADR-026: クローズ済ポジションの意味的アクセサ (booking 待ち判定用)

    field 定義・実測値は docs/api/saxo/closed-position-fields.md を参照。
    """

    def _setup_valid_access(self, db):
        db.save_token(
            provider=PROVIDER, environment="live", token_type="access",
            token_value="AT_valid", expires_at=now_jst() + timedelta(seconds=1200),
        )

    @staticmethod
    def _closed(closing_position_id="7715222483", symbol="SOXL:arcx"):
        """2026-08-19 SOXL 決済の実測レスポンス (12株, $134.13 -> $120.03)。"""
        return {
            "ClosedPositionUniqueId": f"7713499853-{closing_position_id}",
            "NetPositionId": "46780__Share",
            "ClosedPosition": {
                "AccountId": "77800/T126816",
                "Amount": 12.0,
                "AssetType": "Etf",
                "BuyOrSell": "Buy",
                "ClosedProfitLoss": -169.2,
                "ClosedProfitLossInBaseCurrency": -30026.26019115,
                "ClosingMethod": "Fifo",
                "ClosingPositionId": closing_position_id,
                "ClosingPrice": 120.03,
                "CostClosing": -1.3,
                "CostClosingInBaseCurrency": -206.0,
                "CostOpening": -1.42,
                "CostOpeningInBaseCurrency": -227.0,
                "ExecutionTimeClose": "2026-08-19T14:07:32.578000Z",
                "ExecutionTimeOpen": "2026-08-18T13:30:00.246000Z",
                "OpeningPositionId": "7713499853",
                "OpenPrice": 134.13,
                "ProfitLossCurrencyConversion": -2943.65833065,
                "ProfitLossOnTrade": -169.2,
                "ProfitLossOnTradeInBaseCurrency": -27082.6018605,
                "Uic": 46780,
            },
            "DisplayAndFormat": {"Symbol": symbol, "Currency": "USD"},
        }

    def test_returns_semantic_dataclass(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"Data": [self._closed()]})
        closed = client.get_closed_positions()
        assert len(closed) == 1
        c = closed[0]
        assert isinstance(c, ClosedPosition)
        assert c.symbol == "SOXL"
        assert c.amount == 12.0
        assert c.open_price == 134.13
        assert c.closing_price == 120.03
        assert c.closing_position_id == "7715222483"
        assert c.opening_position_id == "7713499853"
        assert c.instrument_currency == "USD"

    def test_opening_side_is_not_the_closing_side(self, client, db, mock_session):
        """罠1: BuyOrSell は建玉を開いた方向。買い建てを売り決済しても 'Buy'。"""
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"Data": [self._closed()]})
        c = client.get_closed_positions()[0]
        assert c.opening_side == "Buy"
        assert c.ledger_side() == "sell"
        assert c.signed_amount() == -12.0

    def test_short_close_maps_to_buy_ledger_side(self, client, db, mock_session):
        """売り建ての決済は台帳 buy 行に対応する (符号反転)。"""
        self._setup_valid_access(db)
        raw = self._closed()
        raw["ClosedPosition"]["BuyOrSell"] = "Sell"
        mock_session.get.return_value = _mock_response(200, {"Data": [raw]})
        c = client.get_closed_positions()[0]
        assert c.ledger_side() == "buy"
        assert c.signed_amount() == 12.0

    def test_all_in_pnl_includes_costs(self, client, db, mock_session):
        """ClosedProfitLoss は手数料を含まない。all_in は Cost* を加算して求める。"""
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"Data": [self._closed()]})
        c = client.get_closed_positions()[0]
        # 恒等式: ClosedProfitLossInBase == pnl_base + fx_conversion
        assert c.closed_pnl_base == pytest.approx(
            c.pnl_base + c.pnl_fx_conversion_base, abs=1e-6)
        # all-in は手数料 (負値) を加算
        assert c.all_in_pnl_base() == pytest.approx(-30026.26019115 - 227.0 - 206.0)

    def test_cost_base_is_positive_magnitude(self, client, db, mock_session):
        """Saxo は Cost* を負値で返す。コスト額として使う絶対値も提供する。"""
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"Data": [self._closed()]})
        c = client.get_closed_positions()[0]
        assert c.total_cost_base() == pytest.approx(433.0)
        assert c.total_cost_instrument() == pytest.approx(2.72)

    def test_symbol_falls_back_to_uic_map(self, client, db, mock_session):
        self._setup_valid_access(db)
        raw = self._closed(symbol=None)
        mock_session.get.return_value = _mock_response(200, {"Data": [raw]})
        assert client.get_closed_positions()[0].symbol == "SOXL"

    def test_empty_when_no_closed_positions(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"Data": []})
        assert client.get_closed_positions() == []

    def test_missing_field_raises(self, client, db, mock_session):
        """required 欠落は黙って 0 埋めせず SaxoAuthError (静かな誤照合を防ぐ)。"""
        self._setup_valid_access(db)
        bad = {"Data": [{"ClosedPosition": {"Uic": 46780, "Amount": 12.0}}]}
        mock_session.get.return_value = _mock_response(200, bad)
        with pytest.raises(SaxoAuthError, match="missing"):
            client.get_closed_positions()

    def test_requests_closedposition_fieldgroup(self, client, db, mock_session):
        """ClosedPosition FieldGroup を要求しないと数量・価格が丸ごと欠落する。"""
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"Data": []})
        client.get_closed_positions()
        url = mock_session.get.call_args[0][0]
        assert "/port/v1/closedpositions/me" in url
        assert "ClosedPosition" in url
        assert "DisplayAndFormat" in url


class TestTradeCost:
    """ADR-029: 取引コスト見積り (break-even) の意味的アクセサ"""

    def _setup_valid_access(self, db):
        db.save_token(
            provider=PROVIDER, environment="live", token_type="access",
            token_value="AT_valid", expires_at=now_jst() + timedelta(seconds=1200),
        )

    @staticmethod
    def _cost_response():
        """2026-06-02 SOXL 3株@$227 (口座 T126816/JPY) の実レスポンス由来"""
        return {
            "AccountCurrency": "JPY",
            "AccountID": "77800/T126816",
            "Amount": 3.0,
            "AssetType": "Etf",
            "Cost": {
                "Long": {
                    "BuySell": "Buy",
                    "Currency": "USD",
                    "HoldingCost": {
                        "Tax": [
                            {"Pct": 0.029, "Value": 0.2,
                             "Rule": {"TargetCostType": "CTaxOnCommission"}},
                            {"Pct": 0.001, "Value": 0.01,
                             "Rule": {"Description": "SEC手数料"}},
                        ]
                    },
                    "TotalCost": 5.92,
                    "TotalCostPct": 0.869,
                    "TradingCost": {
                        "Commissions": [
                            {"Pct": 0.294, "Value": 2.0,
                             "Rule": {"Currency": "USD", "MinCommission": 1.0}},
                        ],
                        "ConversionCost": {"Pct": 0.501, "Value": 3.41,
                                           "Rule": {"Pct": 0.25}},
                        "Spread": {"Pct": 0.044, "Value": 0.3, "Rule": {"Value": 0.1}},
                    },
                }
            },
            "CostCalculationAssumptions": [
                "IncludesOpenAndCloseCost",
                "EquivalentOpenAndClosePrice",
                "ImplicitCostsNotChargedOnAccount",
            ],
            "HoldingPeriodInDays": 0,
            "Instrument": "Direxion Daily Semiconductor Bull 3X ETF",
            "Price": 227.0,
            "Uic": 46780,
        }

    def test_returns_dataclass_with_breakeven(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._cost_response())
        tc = client.get_trade_cost(
            account_key="AK", uic=46780, asset_type="Etf", amount=3, price=227,
        )
        assert isinstance(tc, TradeCost)
        # TotalCostPct = 往復 break-even%
        assert tc.total_cost_pct == 0.869
        assert tc.total_cost == 5.92
        assert tc.is_round_trip is True  # IncludesOpenAndCloseCost
        assert tc.account_currency == "JPY"
        assert tc.instrument_currency == "USD"

    def test_parses_cost_breakdown(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._cost_response())
        tc = client.get_trade_cost(
            account_key="AK", uic=46780, asset_type="Etf", amount=3, price=227,
        )
        # 為替手数料 (円口座の最大コスト要因)
        assert tc.conversion_cost == 3.41
        assert tc.conversion_cost_pct == 0.501
        assert tc.conversion_rate_pct == 0.25  # 片道率
        # 最低手数料の発動を検知できる
        assert tc.commission == 2.0
        assert tc.min_commission == 1.0
        # spread + holding(税)
        assert tc.spread_cost == 0.3
        assert tc.holding_cost == pytest.approx(0.21)  # 0.2 + 0.01

    def test_break_even_price_long_is_above_entry(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._cost_response())
        tc = client.get_trade_cost(
            account_key="AK", uic=46780, asset_type="Etf", amount=3, price=227,
        )
        # long: entry を 0.869% 上回ればコスト回収
        assert tc.break_even_price() == pytest.approx(227 * 1.00869)
        assert tc.break_even_price() > 227

    def test_break_even_price_short_is_below_entry(self, client, db, mock_session):
        self._setup_valid_access(db)
        resp = self._cost_response()
        resp["Cost"]["Short"] = resp["Cost"]["Long"]  # 同構造を Short に流用
        mock_session.get.return_value = _mock_response(200, resp)
        tc = client.get_trade_cost(
            account_key="AK", uic=46780, asset_type="Etf", amount=3, price=227,
            direction="short",
        )
        assert tc.break_even_price() == pytest.approx(227 * (1 - 0.00869))
        assert tc.break_even_price() < 227

    def test_calls_endpoint_with_amount_and_price(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._cost_response())
        client.get_trade_cost(
            account_key="AK1", uic=46780, asset_type="Etf", amount=3, price=227,
        )
        url = mock_session.get.call_args[0][0]
        assert "/cs/v1/tradingconditions/cost/AK1/46780/Etf" in url
        assert "Amount=3" in url
        assert "Price=227" in url

    def test_missing_side_raises(self, client, db, mock_session):
        self._setup_valid_access(db)
        resp = self._cost_response()
        del resp["Cost"]["Long"]  # long side を欠落
        mock_session.get.return_value = _mock_response(200, resp)
        with pytest.raises(SaxoAuthError, match="missing 'Long' side"):
            client.get_trade_cost(
                account_key="AK", uic=46780, asset_type="Etf", amount=3, price=227,
            )

    def test_missing_required_field_raises(self, client, db, mock_session):
        self._setup_valid_access(db)
        resp = self._cost_response()
        del resp["Cost"]["Long"]["TotalCostPct"]
        mock_session.get.return_value = _mock_response(200, resp)
        with pytest.raises(SaxoAuthError, match="missing required fields"):
            client.get_trade_cost(
                account_key="AK", uic=46780, asset_type="Etf", amount=3, price=227,
            )

    def test_invalid_direction_raises(self, client, db):
        with pytest.raises(ValueError, match="direction must be"):
            client.get_trade_cost(
                account_key="AK", uic=46780, asset_type="Etf", amount=3, price=227,
                direction="sideways",
            )


class TestTradeReports:
    """ADR-030: 執行事実層 (account_transactions) の供給源 = reports/trades。

    買売判定は TradeEventType ("Bought"/"Sold")、Amount は符号付。
    結合キーは OrderId (broker_ref)、約定主キーは TradeId。
    docs/api/saxo/trade-report-fields.md 参照。
    """

    def _setup_valid_access(self, db):
        db.save_token(
            provider=PROVIDER, environment="live", token_type="access",
            token_value="AT_valid", expires_at=now_jst() + timedelta(seconds=1200),
        )

    @staticmethod
    def _trades_response():
        # 2026-06-03 live で観測した SOXL 往復 (trade 12 に対応)
        return {
            "__count": 2,
            "Data": [
                {
                    "TradeId": "6732724591", "OrderId": "5409009626",
                    "AccountId": "77800/T126816", "Uic": 46780,
                    "InstrumentSymbol": "SOXL:arcx", "AssetType": "Etf",
                    "Amount": 3.0, "Price": 218.0,
                    "TradeEventType": "Bought", "Direction": "None",
                    "ToOpenOrClose": "ToOpen", "TradeType": "Limit",
                    "TradeDate": "2026-06-01", "ValueDate": "2026-06-02",
                    "TradeExecutionTime": "2026-06-01T13:51:47.737000Z",
                    "BookedAmountUSD": -655.77, "BookedAmountAccountCurrency": -104712.0,
                    "AccountCurrency": "JPY", "SpreadCostUSD": 0.0,
                },
                {
                    "TradeId": "6734709190", "OrderId": "5409035181",
                    "AccountId": "77800/T126816", "Uic": 46780,
                    "InstrumentSymbol": "SOXL:arcx", "AssetType": "Etf",
                    "Amount": -3.0, "Price": 243.18,
                    "TradeEventType": "Sold", "Direction": "None",
                    "ToOpenOrClose": "ToOpen", "TradeType": "Limit",
                    "TradeDate": "2026-06-02", "ValueDate": "2026-06-03",
                    "TradeExecutionTime": "2026-06-02T13:30:00.233000Z",
                    "BookedAmountUSD": 727.05, "BookedAmountAccountCurrency": 116283.0,
                    "AccountCurrency": "JPY", "SpreadCostUSD": 0.0,
                },
            ],
        }

    def test_returns_dataclass_list(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._trades_response())
        reports = client.get_trade_reports(
            client_key="CK", from_date="2026-06-01", to_date="2026-06-03",
        )
        assert len(reports) == 2
        assert all(isinstance(r, TradeReport) for r in reports)

    def test_buy_sell_from_trade_event_type(self, client, db, mock_session):
        """買売は TradeEventType。Direction='None' に依存しない。"""
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._trades_response())
        buy, sell = client.get_trade_reports(
            client_key="CK", from_date="2026-06-01", to_date="2026-06-03",
        )
        assert buy.side == "buy"
        assert buy.quantity == 3.0
        assert buy.order_id == "5409009626"
        assert buy.trade_id == "6732724591"
        assert sell.side == "sell"
        assert sell.quantity == 3.0  # abs(Amount)
        assert sell.price == 243.18

    def test_value_date_is_settlement(self, client, db, mock_session):
        from datetime import date
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._trades_response())
        buy, _ = client.get_trade_reports(
            client_key="CK", from_date="2026-06-01", to_date="2026-06-03",
        )
        assert buy.trade_date == date(2026, 6, 1)
        assert buy.value_date == date(2026, 6, 2)

    def test_booked_amount_signs(self, client, db, mock_session):
        """買=負(cash out)、売=正(cash in)。"""
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._trades_response())
        buy, sell = client.get_trade_reports(
            client_key="CK", from_date="2026-06-01", to_date="2026-06-03",
        )
        assert buy.booked_amount_usd < 0
        assert sell.booked_amount_usd > 0

    def test_passes_query_params(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._trades_response())
        client.get_trade_reports(
            client_key="CK99", from_date="2026-05-01", to_date="2026-06-03",
        )
        url = mock_session.get.call_args[0][0]
        assert "/cs/v1/reports/trades/CK99" in url
        assert "FromDate=2026-05-01" in url
        assert "ToDate=2026-06-03" in url

    def test_unknown_trade_event_type_raises(self, client, db, mock_session):
        self._setup_valid_access(db)
        resp = self._trades_response()
        resp["Data"][0]["TradeEventType"] = "Mystery"
        mock_session.get.return_value = _mock_response(200, resp)
        with pytest.raises(SaxoAuthError, match="TradeEventType"):
            client.get_trade_reports(
                client_key="CK", from_date="2026-06-01", to_date="2026-06-03",
            )

    def test_missing_required_field_raises(self, client, db, mock_session):
        self._setup_valid_access(db)
        resp = self._trades_response()
        del resp["Data"][0]["OrderId"]
        mock_session.get.return_value = _mock_response(200, resp)
        with pytest.raises(SaxoAuthError, match="missing required"):
            client.get_trade_reports(
                client_key="CK", from_date="2026-06-01", to_date="2026-06-03",
            )

    def test_empty_data_returns_empty(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"__count": 0, "Data": []})
        reports = client.get_trade_reports(
            client_key="CK", from_date="2026-06-01", to_date="2026-06-03",
        )
        assert reports == []


class TestBookings:
    """ADR-030 Phase 5: 入出金・現金移動の供給源 = reports/bookings の AssetType='Cash' 行。

    bookings は記帳全エントリ (約定内訳 + 現金移動 + 手数料内訳) を返すため、
    Cash 行のみを抽出する。ETF 行は reports/trades と二重計上になるので除外。
    docs/api/saxo/booking-fields.md 参照。
    """

    def _setup_valid_access(self, db):
        db.save_token(
            provider=PROVIDER, environment="live", token_type="access",
            token_value="AT_valid", expires_at=now_jst() + timedelta(seconds=1200),
        )

    @staticmethod
    def _bookings_response():
        # 2026-06-03 live で観測: Cash 1 件 (口座間振替) + ETF 内訳 1 件 (除外対象)
        return {
            "__count": 2,
            "Data": [
                {
                    "AssetType": "Cash", "BkAmountId": "53283970258",
                    "AccountId": "77800/T126816", "Date": "2026-03-11",
                    "ValueDate": "2026-03-11", "AmountUSD": 314.53,
                    "AmountAccountCurrency": 50000.0, "AccountCurrency": "JPY",
                    "InstrumentSymbol": "CASHINTRTP",
                    "InstrumentDescription": "Interaccount transfer within different client in S",
                },
                {
                    "AssetType": "Etf", "BkAmountId": "53283970300",
                    "AccountId": "77800/T126816", "Date": "2026-06-01",
                    "ValueDate": "2026-06-02", "AmountUSD": -655.77,
                    "AmountAccountCurrency": -104712.0, "AccountCurrency": "JPY",
                    "InstrumentSymbol": "SOXL:arcx",
                    "InstrumentDescription": "Direxion Daily Semiconductor Bull 3X ETF",
                },
            ],
        }

    def test_returns_cash_only_dataclass_list(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._bookings_response())
        bookings = client.get_bookings(
            client_key="CK", from_date="2026-01-01", to_date="2026-06-03",
        )
        assert len(bookings) == 1                       # ETF 行は除外
        assert all(isinstance(b, CashBooking) for b in bookings)
        assert bookings[0].symbol == "CASHINTRTP"

    def test_cash_field_mapping(self, client, db, mock_session):
        from datetime import date
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._bookings_response())
        b = client.get_bookings(
            client_key="CK", from_date="2026-01-01", to_date="2026-06-03",
        )[0]
        assert b.booking_id == "53283970258"
        assert b.account_id == "77800/T126816"
        assert b.date == date(2026, 3, 11)
        assert b.value_date == date(2026, 3, 11)
        assert b.amount_usd == 314.53
        assert b.amount_account_currency == 50000.0
        assert b.account_currency == "JPY"

    def test_passes_query_params(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, self._bookings_response())
        client.get_bookings(
            client_key="CK77", from_date="2026-01-01", to_date="2026-06-03",
        )
        url = mock_session.get.call_args[0][0]
        assert "/cs/v1/reports/bookings/CK77" in url
        assert "FromDate=2026-01-01" in url
        assert "ToDate=2026-06-03" in url

    def test_missing_required_field_raises(self, client, db, mock_session):
        self._setup_valid_access(db)
        resp = self._bookings_response()
        del resp["Data"][0]["AmountUSD"]
        mock_session.get.return_value = _mock_response(200, resp)
        with pytest.raises(SaxoAuthError, match="missing required"):
            client.get_bookings(
                client_key="CK", from_date="2026-01-01", to_date="2026-06-03",
            )

    def test_empty_data_returns_empty(self, client, db, mock_session):
        self._setup_valid_access(db)
        mock_session.get.return_value = _mock_response(200, {"__count": 0, "Data": []})
        assert client.get_bookings(
            client_key="CK", from_date="2026-01-01", to_date="2026-06-03",
        ) == []

    def test_no_cash_rows_returns_empty(self, client, db, mock_session):
        """Cash 行が無ければ空 (ETF だけの期間)。"""
        self._setup_valid_access(db)
        resp = self._bookings_response()
        resp["Data"] = [r for r in resp["Data"] if r["AssetType"] != "Cash"]
        mock_session.get.return_value = _mock_response(200, resp)
        assert client.get_bookings(
            client_key="CK", from_date="2026-01-01", to_date="2026-06-03",
        ) == []
