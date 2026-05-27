"""Saxo OpenAPI クライアント (ADR-025)

OAuth 2.0 Authorization Code grant + refresh フロー。
access token は 20分で失効するため自動 refresh。
refresh token は rotation するため refresh ごとに DB に新規保存・旧 refresh は revoke。

トークン保管は DuckDB `auth_tokens` テーブル (ADR-025)。
App Key / Secret は .env (静的config と動的state を分離)。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

from src.db import SenseiDB, now_jst

load_dotenv(Path(__file__).parent.parent / ".env")
logger = logging.getLogger(__name__)

PROVIDER = "saxo"

# refresh buffer: access token expiry が これより近づいたら refresh する
ACCESS_TOKEN_REFRESH_BUFFER_SEC = 60

DEFAULT_TIMEOUT_SEC = 10

# Saxo API base URL (REST). 公式: https://www.developer.saxo/openapi/learn/environments
BASE_URL_LIVE = "https://gateway.saxobank.com/openapi"
BASE_URL_SIM = "https://gateway.saxobank.com/sim/openapi"

# refresh token expiry が response に含まれない場合のデフォルト (90日、Saxo 仕様の典型値)
DEFAULT_REFRESH_TOKEN_LIFETIME_SEC = 86400 * 90


class SaxoAuthError(Exception):
    """OAuth 認証フローのエラー"""


@dataclass
class AccountBalance:
    """口座別の意味的 balance snapshot (ADR-026)。

    raw dict キー access を防ぐためのインタフェース。各フィールドの
    公式定義は docs/api/saxo/balance-fields.md を参照。

    Attributes:
        spending_power: 取引可能額 (sizing 判断に使う)。
            CashAvailableForTrading と通常同値、未決済込み。
        cash_available_for_trading: 同上 (互換性のため別名)。
        settled_cash_balance: settled cash のみ。**sizing には使わない** (未決済を
            含まないため過小評価)。会計表示用途のみ。
        total_value: NAV (cash + 未実現ポジション評価額)。
        unrealized_pnl: 含み損益。
        transactions_not_booked: T+2 未決済額 (debug 用)。
        open_positions_count: open position 数。
        net_positions_count: open + settling closed の合計。
        non_margin_positions_value: cash instrument の合計評価額。
        calculation_reliability: "Ok" 以外は調査必要。
    """
    account_id: str
    account_key: str
    currency: str
    spending_power: float
    cash_available_for_trading: float
    settled_cash_balance: float
    total_value: float
    unrealized_pnl: float
    transactions_not_booked: float
    open_positions_count: int
    net_positions_count: int
    non_margin_positions_value: float
    calculation_reliability: str


@dataclass
class SaxoConfig:
    app_key: str
    app_secret: str
    auth_url: str
    token_url: str
    redirect_uri: str
    environment: str  # 'sim' | 'live'
    base_url: str

    @classmethod
    def from_env(cls, environment: Optional[str] = None) -> SaxoConfig:
        env = (environment or os.environ.get("SAXO_ENVIRONMENT", "live")).lower()
        if env not in {"sim", "live"}:
            raise ValueError(f"SAXO_ENVIRONMENT must be 'sim' or 'live', got '{env}'")

        suffix = env.upper()
        keys = {
            f"SAXO_APP_KEY_{suffix}": os.environ.get(f"SAXO_APP_KEY_{suffix}"),
            f"SAXO_APP_SECRET_{suffix}": os.environ.get(f"SAXO_APP_SECRET_{suffix}"),
            f"SAXO_AUTH_URL_{suffix}": os.environ.get(f"SAXO_AUTH_URL_{suffix}"),
            f"SAXO_TOKEN_URL_{suffix}": os.environ.get(f"SAXO_TOKEN_URL_{suffix}"),
            "SAXO_REDIRECT_URI": os.environ.get("SAXO_REDIRECT_URI"),
        }
        missing = [name for name, val in keys.items() if not val]
        if missing:
            raise ValueError(f"Missing required env vars: {missing}")

        for url_key in (f"SAXO_AUTH_URL_{suffix}", f"SAXO_TOKEN_URL_{suffix}"):
            url_val = keys[url_key]
            if not url_val.startswith("https://"):
                raise ValueError(
                    f"{url_key} must use https:// scheme (credentials transmitted via Basic Auth); "
                    f"got {url_val!r}"
                )

        base_url = BASE_URL_SIM if env == "sim" else BASE_URL_LIVE
        return cls(
            app_key=keys[f"SAXO_APP_KEY_{suffix}"],
            app_secret=keys[f"SAXO_APP_SECRET_{suffix}"],
            auth_url=keys[f"SAXO_AUTH_URL_{suffix}"],
            token_url=keys[f"SAXO_TOKEN_URL_{suffix}"],
            redirect_uri=keys["SAXO_REDIRECT_URI"],
            environment=env,
            base_url=base_url,
        )


class SaxoClient:
    """Saxo OpenAPI 用 OAuth クライアント + Portfolio API ラッパー

    Usage:
        db = SenseiDB(conn)
        client = SaxoClient(db)
        balances = client.get_balances()
        positions = client.get_positions()
    """

    def __init__(self, db: SenseiDB, config: Optional[SaxoConfig] = None,
                 session: Optional[requests.Session] = None):
        self.db = db
        self.config = config or SaxoConfig.from_env()
        self._session = session or requests.Session()

    # ── OAuth flow ──

    def build_authorization_url(self, state: str) -> str:
        """初回認可で使う URL を生成。ブラウザで開いてユーザにログインしてもらう。"""
        params = {
            "response_type": "code",
            "client_id": self.config.app_key,
            "redirect_uri": self.config.redirect_uri,
            "state": state,
        }
        return f"{self.config.auth_url}?{urlencode(params)}"

    def exchange_code_for_tokens(self, code: str) -> dict:
        """OAuth callback で受け取った code を access+refresh token に交換し DB 保存"""
        resp = self._session.post(
            self.config.token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
            },
            auth=(self.config.app_key, self.config.app_secret),
            timeout=DEFAULT_TIMEOUT_SEC,
        )
        if not resp.ok:
            raise SaxoAuthError(
                f"Initial token exchange failed: HTTP {resp.status_code}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise SaxoAuthError(
                f"Token endpoint returned non-JSON response: HTTP {resp.status_code}"
            ) from exc
        if "refresh_token" not in data:
            raise SaxoAuthError(
                "Token endpoint did not return refresh_token. "
                "Check OAuth app scope/grant type configuration on Saxo Developer Portal."
            )
        self._persist_token_response(data, acquired_via="oauth_initial", prev_refresh_count=0)
        logger.info("Saxo OAuth initial tokens persisted (env=%s)", self.config.environment)
        return data

    def get_access_token(self) -> str:
        """有効な access token を返す。失効間際なら refresh。"""
        token = self.db.get_active_token(
            provider=PROVIDER,
            environment=self.config.environment,
            token_type="access",
        )
        if token and self._token_has_buffer(token):
            return token["token_value"]
        return self._refresh_access_token()

    def _token_has_buffer(self, token: dict) -> bool:
        remaining = token["expires_at"] - now_jst()
        return remaining > timedelta(seconds=ACCESS_TOKEN_REFRESH_BUFFER_SEC)

    def _refresh_access_token(self) -> str:
        refresh_row = self.db.get_active_token(
            provider=PROVIDER,
            environment=self.config.environment,
            token_type="refresh",
        )
        if refresh_row is None:
            raise SaxoAuthError(
                "No valid refresh token. "
                "Run `python scripts/saxo_oauth_init.py` to re-authenticate."
            )

        resp = self._session.post(
            self.config.token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_row["token_value"],
                "redirect_uri": self.config.redirect_uri,
            },
            auth=(self.config.app_key, self.config.app_secret),
            timeout=DEFAULT_TIMEOUT_SEC,
        )
        if not resp.ok:
            # Only revoke on definitive auth failures (invalid_grant / unauthorized).
            # 5xx and 429 are transient — keep refresh token so caller can retry later.
            if self._is_definitive_auth_failure(resp):
                self.db.revoke_token(
                    refresh_row["id"], reason=f"refresh_http_{resp.status_code}"
                )
            raise SaxoAuthError(
                f"Token refresh failed: HTTP {resp.status_code}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise SaxoAuthError(
                f"Token refresh returned non-JSON response: HTTP {resp.status_code}"
            ) from exc
        prev_count = refresh_row["refresh_count"]
        self._persist_token_response(
            data,
            acquired_via="oauth_refresh",
            prev_refresh_count=prev_count,
            old_refresh_id=refresh_row["id"],
            old_refresh_value=refresh_row["token_value"],
        )
        logger.info("Saxo access token refreshed (env=%s, count=%d)",
                    self.config.environment, prev_count + 1)
        return data["access_token"]

    @staticmethod
    def _is_definitive_auth_failure(resp: requests.Response) -> bool:
        """refresh token を revoke すべき definitive failure か判定。

        判定基準:
        - HTTP 401: 認証失敗 (token 無効)
        - HTTP 400 with body containing OAuth error code 'invalid_grant' / 'invalid_request'
          / 'unauthorized_client' (refresh token 無効化が確定するケース)
        - その他 4xx は曖昧、保守的に definitive 扱い
        - 5xx, 429 (rate limit), その他 transient は revoke しない

        See https://datatracker.ietf.org/doc/html/rfc6749#section-5.2
        """
        if resp.status_code == 429 or resp.status_code >= 500:
            return False
        if resp.status_code == 401:
            return True
        if resp.status_code == 400:
            try:
                error_code = (resp.json() or {}).get("error", "")
            except ValueError:
                error_code = ""
            return error_code in {
                "invalid_grant", "invalid_request", "unauthorized_client",
                "unsupported_grant_type",
            }
        # その他 4xx は保守的に revoke (network proxy, malformed request 等)
        return 400 <= resp.status_code < 500

    def _persist_token_response(
        self,
        data: dict,
        *,
        acquired_via: str,
        prev_refresh_count: int,
        old_refresh_id: Optional[int] = None,
        old_refresh_value: Optional[str] = None,
    ) -> None:
        """token endpoint response から access + refresh を DB 保存。
        rotation が発生していれば旧 refresh を revoke。"""
        required = ("access_token", "expires_in")
        missing = [k for k in required if k not in data]
        if missing:
            raise SaxoAuthError(
                f"Token response missing required keys {missing} "
                f"(present keys: {sorted(data.keys())})"
            )
        try:
            expires_in_sec = int(data["expires_in"])
        except (TypeError, ValueError) as exc:
            raise SaxoAuthError(
                f"Token response has invalid expires_in: {data['expires_in']!r}"
            ) from exc

        anchor = now_jst()
        access_value = data["access_token"]
        access_expires = anchor + timedelta(seconds=expires_in_sec)
        new_refresh_value = data.get("refresh_token")
        try:
            refresh_lifetime = int(data.get("refresh_token_expires_in",
                                             DEFAULT_REFRESH_TOKEN_LIFETIME_SEC))
        except (TypeError, ValueError):
            refresh_lifetime = DEFAULT_REFRESH_TOKEN_LIFETIME_SEC
        refresh_expires = anchor + timedelta(seconds=refresh_lifetime)

        # access token は常に新規保存
        self.db.save_token(
            provider=PROVIDER,
            environment=self.config.environment,
            token_type="access",
            token_value=access_value,
            expires_at=access_expires,
            acquired_via=acquired_via,
            refresh_count=prev_refresh_count + (1 if acquired_via == "oauth_refresh" else 0),
            metadata=json.dumps({"response_keys": sorted(data.keys())}),
        )

        # refresh token: rotation が発生していれば保存 + 旧 revoke
        if new_refresh_value and new_refresh_value != old_refresh_value:
            self.db.save_token(
                provider=PROVIDER,
                environment=self.config.environment,
                token_type="refresh",
                token_value=new_refresh_value,
                expires_at=refresh_expires,
                acquired_via=acquired_via,
                refresh_count=prev_refresh_count + (1 if acquired_via == "oauth_refresh" else 0),
                metadata=json.dumps({"response_keys": sorted(data.keys())}),
            )
            if old_refresh_id is not None:
                self.db.revoke_token(old_refresh_id, reason="rotated_on_refresh")

    # ── Portfolio API (read-only) ──

    def get_balances(self) -> dict:
        """aggregated balance (全 sub-account 合算、base currency 換算)。raw dict 返却。

        ⚠️ **sizing 判断には使わない**。
          - 口座別の取引余力は `get_account_balance()` 経由で取得すること。
          - dict キー直接 access (`["CashBalance"]` 等) も禁止 (ADR-026)。

        この method は schema 確認・field 探索など調査用途のみ。

        See docs/api/saxo/endpoints.md#2-get-portv1balancesme
        """
        return self._api_get("/port/v1/balances/me")

    def get_positions(self) -> list[dict]:
        """open positions のリストを返す (Data 配列、raw dict)。

        See docs/api/saxo/endpoints.md#4-get-portv1positionsme
        """
        return self._api_get("/port/v1/positions/me").get("Data", [])

    def get_accounts(self) -> list[dict]:
        """全 sub-account 一覧 (Data 配列、raw dict)。

        See docs/api/saxo/endpoints.md#1-get-portv1accountsme
        """
        return self._api_get("/port/v1/accounts/me").get("Data", [])

    def get_account_balance(self, account_key: str, client_key: str,
                            account_id: str = "") -> AccountBalance:
        """口座別の意味的 balance snapshot を返す (推奨インタフェース)。

        sizing 判断 (例: SOXL 何株買えるか) は `result.spending_power` を使うこと。
        `result.settled_cash_balance` は会計表示用、sizing には使わない (未決済を含まない)。

        ADR-026 に基づき raw dict 露出を防ぐ。新規 field が必要な場合は
        `AccountBalance` dataclass を拡張し、`docs/api/saxo/balance-fields.md` に
        該当 field の公式定義を追記すること (citation 必須)。

        See docs/api/saxo/balance-fields.md
        """
        bal = self._api_get(
            f"/port/v1/balances?AccountKey={account_key}&ClientKey={client_key}"
        )
        required = (
            "Currency", "SpendingPower", "CashAvailableForTrading", "CashBalance",
            "TotalValue", "UnrealizedPositionsValue", "TransactionsNotBooked",
            "OpenPositionsCount", "NetPositionsCount", "NonMarginPositionsValue",
            "CalculationReliability",
        )
        missing = [k for k in required if k not in bal]
        if missing:
            raise SaxoAuthError(
                f"Balance response missing required fields {missing} "
                f"for account {account_id or account_key}. "
                "Saxo API may have changed; verify docs/api/saxo/balance-fields.md"
            )
        return AccountBalance(
            account_id=account_id,
            account_key=account_key,
            currency=bal["Currency"],
            spending_power=float(bal["SpendingPower"]),  # see balance-fields.md#spendingpower
            cash_available_for_trading=float(bal["CashAvailableForTrading"]),  # see #cashavailablefortrading
            settled_cash_balance=float(bal["CashBalance"]),  # see #cashbalance
            total_value=float(bal["TotalValue"]),  # see #totalvalue
            unrealized_pnl=float(bal["UnrealizedPositionsValue"]),  # see #unrealizedpositionsvalue
            transactions_not_booked=float(bal["TransactionsNotBooked"]),  # see #transactionsnotbooked
            open_positions_count=int(bal["OpenPositionsCount"]),  # see #openpositionscount
            net_positions_count=int(bal["NetPositionsCount"]),  # see #netpositionscount
            non_margin_positions_value=float(bal["NonMarginPositionsValue"]),  # see #nonmarginpositionsvalue
            calculation_reliability=bal["CalculationReliability"],  # see #calculationreliability
        )

    def get_all_account_balances(self) -> list[AccountBalance]:
        """全 active sub-account の意味的 balance を取得。

        AccountBalance.account_id で各口座を識別できる (P120136 / T126816 等)。

        See docs/api/saxo/balance-fields.md
        """
        accounts = self.get_accounts()
        results: list[AccountBalance] = []
        for a in accounts:
            if not a.get("Active"):
                continue
            balance = self.get_account_balance(
                account_key=a["AccountKey"],
                client_key=a["ClientKey"],
                account_id=a["AccountId"],
            )
            results.append(balance)
        return results

    def _api_get(self, path: str) -> dict:
        token = self.get_access_token()
        url = self.config.base_url + path
        resp = self._session.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=DEFAULT_TIMEOUT_SEC,
        )
        if resp.status_code == 401:
            raise SaxoAuthError(
                f"401 from {path}. Token may be invalid or revoked server-side. "
                "Try re-authenticating via scripts/saxo_oauth_init.py"
            )
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError as exc:
            raise SaxoAuthError(
                f"Non-JSON response from {path}: HTTP {resp.status_code}"
            ) from exc
