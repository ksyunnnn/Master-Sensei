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
from datetime import date, timedelta
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


# Saxo の Uic は instrument 固有で安定。本プロジェクトの取引ユニバース (ADR-004)
# について live ポジション/cost endpoint で検証済みの値。新規 symbol は
# /ref/v1/instruments で解決すること (未実装、必要時に追加)。
# 検証: 2026-06-02 live position (SOXL) + cost endpoint 実コール
SAXO_UIC = {
    "SOXL": (46780, "Etf"),
}

# Uic → symbol 逆引き (DisplayAndFormat.Symbol が取れない時の fallback)。
_SYMBOL_BY_UIC = {uic: sym for sym, (uic, _atype) in SAXO_UIC.items()}


def _normalize_symbol(raw_symbol, uic: int) -> str:
    """`DisplayAndFormat.Symbol` ("SOXL:arcx") を照合用 symbol ("SOXL") に正規化。

    1. raw_symbol があれば ":" 前を採用 (取引所サフィックス除去)
    2. なければ SAXO_UIC 逆引き
    3. それも無ければ "UIC:<n>" (未知 instrument として照合で可視化)

    See docs/api/saxo/position-fields.md, order-fields.md。
    """
    if raw_symbol:
        return str(raw_symbol).split(":")[0]
    if uic in _SYMBOL_BY_UIC:
        return _SYMBOL_BY_UIC[uic]
    return f"UIC:{uic}"


@dataclass
class LivePosition:
    """ライブ open position の意味的 snapshot (ADR-026)。

    raw dict access を防ぐ。公式 field 定義は docs/api/saxo/position-fields.md。
    `/sync-saxo` の live↔台帳照合に使う。照合は **net 数量 (`amount`)** のみで行い、
    価格は使わない。
    """
    account_id: str
    uic: int
    symbol: str
    amount: float            # 正=long, 負=short
    open_price: float
    unrealized_pnl_base: float   # ProfitLossOnTradeInBaseCurrency (base=JPY)


@dataclass
class OpenOrder:
    """ライブ未約定注文 (working order) の意味的 snapshot (ADR-026)。

    公式 field 定義は docs/api/saxo/order-fields.md。結合キーは `order_id`
    (↔ trades.broker_ref)。placed 注文は fill が無く台帳照合では出ないため、
    この snapshot が注文ドリフト検出の唯一の源。
    """
    order_id: str
    account_id: str
    uic: int
    symbol: str
    amount: float
    buy_sell: str | None     # "Buy"/"Sell"。脚で欠落時は None (向きを推測しない)
    order_type: str          # OpenOrderType (Limit/Stop/...)
    price: float | None      # 指値/逆指値価格 (Market は None)
    status: str
    # IFD-OCO の保護脚は親の RelatedOpenOrders[] にネストされる (issue#16)。
    # 脚は parent_order_id を持ち、instrument/口座/数量は親から引き継ぐ
    # (同一銘柄の決済注文なので構造的に同じ。推測ではない)。
    order_relation: str | None = None   # IfDoneMaster / Oco / StandAlone 等
    parent_order_id: str | None = None  # 脚の場合のみ親 OrderId


@dataclass
class ClosedPosition:
    """決済済ポジション (open→close ペア) の意味的 snapshot (ADR-026)。

    公式 field 定義・実測値は docs/api/saxo/closed-position-fields.md。
    `reports/trades` の booking は T+1 だが本層は**決済当日に返る**ため、
    `/sync-saxo` の「台帳に余分」break を booking 待ちか真の乖離かに切り分ける。

    **`OrderId` を持たない**ので `trades.broker_ref` と 1対1 結合できない
    (`*_position_id` は PositionId であって OrderId ではない)。照合は
    instrument 単位の数量合計に留める。

    Attributes:
        opening_side: **建玉を開いた方向** ("Buy"/"Sell")。決済の方向ではない。
            台帳側の行種別は `ledger_side()` で反転して求める。
        pnl_instrument / pnl_base: 価格変動のみの損益 (instrument 通貨 / 口座通貨)。
        pnl_fx_conversion_base: FX 変換損益 (口座通貨)。円口座 × USD 建で発生する
            独立コスト源で、価格変動損益とは別に効く。
        closed_pnl_*: 実現損益 (**手数料を含まない**)。all-in は `all_in_pnl_base()`。
        cost_*: Saxo は**負値**で返す (原文保持)。コスト額は `total_cost_*()`。
    """
    unique_id: str
    account_id: str
    uic: int
    symbol: str
    amount: float                    # 決済数量 (常に正)
    opening_side: str                # "Buy"/"Sell" = 建玉を開いた方向
    open_price: float
    closing_price: float
    execution_time_open_utc: str     # UTC ISO8601 原文
    execution_time_close_utc: str    # UTC ISO8601 原文
    opening_position_id: str         # PositionId (OrderId ではない)
    closing_position_id: str         # PositionId (OrderId ではない)
    pnl_instrument: float
    pnl_base: float
    pnl_fx_conversion_base: float
    closed_pnl_instrument: float
    closed_pnl_base: float
    cost_opening_instrument: float   # 負値
    cost_closing_instrument: float   # 負値
    cost_opening_base: float         # 負値
    cost_closing_base: float         # 負値
    closing_method: str
    asset_type: str
    instrument_currency: str

    def ledger_side(self) -> str:
        """この決済が台帳 (account_transactions) に生む行の種別を返す。

        買い建ての決済は sell 行、売り建ての決済は buy 行になる
        (`opening_side` は建玉方向なので反転する)。
        """
        return "sell" if self.opening_side == "Buy" else "buy"

    def signed_amount(self) -> float:
        """台帳 net 数量への寄与 (buy=+ / sell=−)。"""
        return -self.amount if self.ledger_side() == "sell" else self.amount

    def total_cost_instrument(self) -> float:
        """往復コストの絶対額 (instrument 通貨)。"""
        return abs(self.cost_opening_instrument) + abs(self.cost_closing_instrument)

    def total_cost_base(self) -> float:
        """往復コストの絶対額 (口座通貨)。"""
        return abs(self.cost_opening_base) + abs(self.cost_closing_base)

    def all_in_pnl_base(self) -> float:
        """手数料込みの実現損益 (口座通貨)。

        `closed_pnl_base` は手数料を含まないので `cost_*_base` (負値) を加算する。
        """
        return self.closed_pnl_base + self.cost_opening_base + self.cost_closing_base


@dataclass
class TradeCost:
    """単一銘柄・サイズの往復取引コスト見積り (ADR-029)。

    Saxo `/cs/v1/tradingconditions/cost` の `Cost.Long`/`Cost.Short` を意味的に
    展開する。`is_round_trip` が True (= 応答に `IncludesOpenAndCloseCost`) のとき、
    `total_cost_pct` は **往復 (open+close) コスト = break-even 値幅%** を表す。

    raw dict access を防ぐ (ADR-026)。各 field の公式定義・実レスポンス例は
    docs/api/saxo/cost-fields.md を参照。

    Attributes:
        total_cost: 往復コスト絶対額 (instrument_currency)。
        total_cost_pct: 往復コスト÷notional の % = break-even 値幅% (round-trip 時)。
        is_round_trip: 見積りが open+close を含むか (CostCalculationAssumptions)。
        commission / commission_pct / min_commission: 売買手数料 (片道 × 往復)。
            min_commission 発動時は notional が小さいほど commission_pct が上昇。
        conversion_cost / conversion_cost_pct / conversion_rate_pct: 為替手数料。
            account_currency≠instrument_currency (円口座×USD建) で発生。
            conversion_rate_pct は片道率 (例 0.25)。米ドル口座なら 0。
        spread_cost / spread_pct: bid/ask スプレッド (implicit cost)。
        holding_cost: 保有コスト合計絶対額 (税・SEC手数料等、HoldingCost.Tax の合算)。
        assumptions: Saxo の前提リスト (round-trip 判定等の根拠)。
    """
    instrument: str
    uic: int
    asset_type: str
    direction: str            # "long" | "short"
    amount: float
    price: float
    account_currency: str     # 口座通貨 (例 JPY)
    instrument_currency: str  # 建玉通貨 (例 USD)
    total_cost: float
    total_cost_pct: float
    is_round_trip: bool
    commission: float
    commission_pct: float
    min_commission: float
    conversion_cost: float
    conversion_cost_pct: float
    conversion_rate_pct: float
    spread_cost: float
    spread_pct: float
    holding_cost: float
    assumptions: list

    def break_even_price(self) -> float:
        """コストを回収できる価格。long は上方向、short は下方向。

        total_cost_pct が往復%なので、long は entry を total_cost_pct% 上回れば
        break-even。is_round_trip=False の場合は片道コスト基準になる点に注意。
        """
        factor = self.total_cost_pct / 100.0
        if self.direction == "long":
            return self.price * (1 + factor)
        return self.price * (1 - factor)


@dataclass
class TradeReport:
    """実約定1件 (fill) の意味的 snapshot (ADR-030)。

    `GET /cs/v1/reports/trades/{ClientKey}` の Data[] を展開する。執行事実層
    `account_transactions` (Parquet) の供給源。raw dict access を防ぐ (ADR-026)。
    各 field の定義・観測値は docs/api/saxo/trade-report-fields.md を参照。

    Attributes:
        trade_id: 約定の一意 ID (TradeId)。account_transactions の主キー。
        order_id: この約定を生んだ注文 ID (OrderId)。**trades.broker_ref との
            結合キー**。1 order が複数 fill を生むため fill 単位では重複しうる。
        side: "buy" / "sell"。**TradeEventType ("Bought"/"Sold") から決定**。
            Saxo の Direction field は "None" を返すため使わない。
        quantity: 約定数量 (abs(Amount))。
        amount_signed: 符号付数量 (正=買, 負=売)。
        price: 約定単価 (instrument 通貨)。
        trade_date: 約定日。
        value_date: 受渡日 (settlement)。
        execution_time_utc: 約定時刻 (UTC ISO8601 文字列、原文保持)。
        booked_amount_usd: 記帳額 USD (買=負/cash out, 売=正/cash in)。
        booked_amount_account_currency: 記帳額 (口座通貨)。
        account_currency: 口座通貨 (例 JPY)。
        instrument_symbol: "SYMBOL:exchange" (例 "SOXL:arcx")。
        uic: instrument 一意 ID。
        asset_type: "Etf" 等。
        spread_cost_usd: spread コスト (USD)。
    """
    trade_id: str
    order_id: str
    account_id: str
    side: str
    quantity: float
    amount_signed: float
    price: float
    trade_date: date
    value_date: date
    execution_time_utc: str
    booked_amount_usd: float
    booked_amount_account_currency: float
    account_currency: str
    instrument_symbol: str
    uic: int
    asset_type: str
    spread_cost_usd: float


@dataclass
class CashBooking:
    """現金移動1件 (deposit/withdrawal) の意味的 snapshot (ADR-030 Phase 5)。

    `GET /cs/v1/reports/bookings/{ClientKey}` の `Data[]` のうち `AssetType='Cash'`
    の行を展開する。執行事実層 `account_transactions` の入出金行の供給源。
    raw dict access を防ぐ (ADR-026)。各 field の定義・観測値は
    docs/api/saxo/booking-fields.md を参照。

    Attributes:
        booking_id: 記帳エントリの一意 ID (BkAmountId)。現金行の主キー (TradeId は無い)。
        account_id: 口座 (例 77800/T126816)。
        date: 記帳日。
        value_date: 受渡日 (settlement)。
        amount_usd: USD 換算額。**符号付 (+ = cash in / deposit, − = cash out)**。
        amount_account_currency: 口座通貨での額。
        account_currency: 口座通貨 (例 JPY)。
        symbol: 現金種別コード (例 CASHINTRTP = 口座間振替)。元の性質を保持。
        description: 説明文 (例 "Interaccount transfer...")。
    """

    booking_id: str
    account_id: str
    date: date
    value_date: date
    amount_usd: float
    amount_account_currency: float
    account_currency: str
    symbol: str
    description: str


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

    def get_live_positions(self) -> list["LivePosition"]:
        """ライブ open positions を意味的 snapshot のリストで返す (ADR-026)。

        `/sync-saxo` の live↔台帳照合 (`SenseiDB.reconcile_live_positions`) に使う。
        `?FieldGroups=PositionBase,DisplayAndFormat,PositionView` で
        建玉コア(Amount/OpenPrice)・symbol・含み損益を取得する。PositionBase を
        要求しないとパーサが読む AccountId/Uic/Amount/OpenPrice が欠落し、建玉が
        1件でもあれば下記 required チェックで `SaxoAuthError` になる。
        required field 欠落時は `SaxoAuthError` (静かな誤照合を防ぐ)。

        See docs/api/saxo/position-fields.md
        """
        resp = self._api_get(
            "/port/v1/positions/me"
            "?FieldGroups=PositionBase,DisplayAndFormat,PositionView"
        )
        out: list[LivePosition] = []
        for p in resp.get("Data", []):
            base = p.get("PositionBase", {})
            required = ("AccountId", "Uic", "Amount", "OpenPrice")
            missing = [k for k in required if k not in base]
            if missing:
                raise SaxoAuthError(
                    f"Position response missing PositionBase fields {missing}. "
                    "Saxo API may have changed; verify docs/api/saxo/position-fields.md"
                )
            view = p.get("PositionView", {})
            daf = p.get("DisplayAndFormat", {})
            uic = int(base["Uic"])
            out.append(LivePosition(
                account_id=base["AccountId"],  # see position-fields.md
                uic=uic,
                symbol=_normalize_symbol(daf.get("Symbol"), uic),
                amount=float(base["Amount"]),
                open_price=float(base["OpenPrice"]),
                unrealized_pnl_base=float(
                    view.get("ProfitLossOnTradeInBaseCurrency", 0.0) or 0.0),
            ))
        return out

    def get_open_orders(self) -> list["OpenOrder"]:
        """ライブ未約定注文を意味的 snapshot のリストで返す (ADR-026)。

        `/sync-saxo` の注文ドリフト照合 (`SenseiDB.reconcile_open_orders`) に使う。
        placed 注文は fill が無く台帳照合では出ないため、この snapshot が唯一の検出源。
        required field 欠落時は `SaxoAuthError`。

        See docs/api/saxo/order-fields.md
        """
        resp = self._api_get("/port/v1/orders/me?FieldGroups=DisplayAndFormat")
        out: list[OpenOrder] = []
        for o in resp.get("Data", []):
            required = ("OrderId", "AccountId", "Uic", "Amount", "BuySell",
                        "OpenOrderType", "Status")
            missing = [k for k in required if k not in o]
            if missing:
                raise SaxoAuthError(
                    f"Order response missing required fields {missing}. "
                    "Saxo API may have changed; verify docs/api/saxo/order-fields.md"
                )
            daf = o.get("DisplayAndFormat", {})
            uic = int(o["Uic"])
            parent = OpenOrder(
                order_id=str(o["OrderId"]),  # see order-fields.md
                account_id=o["AccountId"],
                uic=uic,
                symbol=_normalize_symbol(daf.get("Symbol"), uic),
                amount=float(o["Amount"]),
                buy_sell=o["BuySell"],
                order_type=o["OpenOrderType"],
                price=float(o["Price"]) if o.get("Price") is not None else None,
                status=o["Status"],
                order_relation=o.get("OrderRelation"),
            )
            out.append(parent)
            out.extend(self._related_legs(o, parent))
        return out

    @staticmethod
    def _related_legs(raw_parent: dict, parent: "OpenOrder") -> list["OpenOrder"]:
        """親注文にネストされた保護脚 (RelatedOpenOrders[]) を展開する (issue#16)。

        IFD-OCO では親が未約定の間、決済指値/決済逆指値は `Data[]` のトップレベルに
        現れず親の配下に入る。走査しないと**保護の無い建玉と誤読する**。

        脚の価格 field は `Price` でなく **`OrderPrice`**。
        instrument/口座/数量は親から引き継ぐ (同一銘柄の決済注文なので構造的に同じ)。
        `BuySell` が無い脚は向きを推測せず None にする (ADR-026)。

        See docs/api/saxo/order-fields.md
        """
        legs: list[OpenOrder] = []
        for leg in raw_parent.get("RelatedOpenOrders") or []:
            if "OrderId" not in leg:
                raise SaxoAuthError(
                    "RelatedOpenOrders entry missing required field ['OrderId']. "
                    "Saxo API may have changed; verify docs/api/saxo/order-fields.md"
                )
            price = leg.get("OrderPrice", leg.get("Price"))
            legs.append(OpenOrder(
                order_id=str(leg["OrderId"]),
                account_id=leg.get("AccountId", parent.account_id),
                uic=int(leg["Uic"]) if "Uic" in leg else parent.uic,
                symbol=parent.symbol,
                amount=float(leg["Amount"]) if "Amount" in leg else parent.amount,
                buy_sell=leg.get("BuySell"),
                order_type=leg.get("OpenOrderType", ""),
                price=float(price) if price is not None else None,
                status=leg.get("Status", ""),
                order_relation=leg.get("OrderRelation"),
                parent_order_id=parent.order_id,
            ))
        return legs

    def get_closed_positions(self) -> list["ClosedPosition"]:
        """決済済ポジションを意味的 snapshot のリストで返す (ADR-026)。

        `reports/trades` の booking は T+1 だが本層は**決済当日に返る**。
        `/sync-saxo` の「台帳に余分」break が booking 待ちか真の乖離かの切り分けに使う
        (`SenseiDB.explain_ledger_surplus_by_closed_positions`)。
        全履歴は返らない (直近の未決済分のみ) ので成績集計には使わない。

        `?FieldGroups=ClosedPosition,DisplayAndFormat` は必須。ClosedPosition を
        要求しないと数量・価格・損益が丸ごと欠落する (positions の PositionBase と同型)。
        required field 欠落時は `SaxoAuthError` (静かな誤照合を防ぐ)。

        See docs/api/saxo/closed-position-fields.md
        """
        resp = self._api_get(
            "/port/v1/closedpositions/me"
            "?FieldGroups=ClosedPosition,DisplayAndFormat"
        )
        out: list[ClosedPosition] = []
        for item in resp.get("Data", []):
            cp = item.get("ClosedPosition", {})
            required = ("AccountId", "Uic", "Amount", "BuyOrSell", "OpenPrice",
                        "ClosingPrice", "ExecutionTimeClose",
                        "OpeningPositionId", "ClosingPositionId")
            missing = [k for k in required if k not in cp]
            if missing:
                raise SaxoAuthError(
                    f"ClosedPosition response missing fields {missing}. "
                    "Saxo API may have changed; verify "
                    "docs/api/saxo/closed-position-fields.md"
                )
            daf = item.get("DisplayAndFormat", {})
            uic = int(cp["Uic"])
            out.append(ClosedPosition(
                unique_id=str(item.get("ClosedPositionUniqueId", "")),
                account_id=cp["AccountId"],  # see closed-position-fields.md
                uic=uic,
                symbol=_normalize_symbol(daf.get("Symbol"), uic),
                amount=abs(float(cp["Amount"])),
                opening_side=cp["BuyOrSell"],  # 建玉方向。決済方向ではない
                open_price=float(cp["OpenPrice"]),
                closing_price=float(cp["ClosingPrice"]),
                execution_time_open_utc=str(cp.get("ExecutionTimeOpen", "")),
                execution_time_close_utc=str(cp["ExecutionTimeClose"]),
                opening_position_id=str(cp["OpeningPositionId"]),
                closing_position_id=str(cp["ClosingPositionId"]),
                pnl_instrument=float(cp.get("ProfitLossOnTrade", 0.0) or 0.0),
                pnl_base=float(cp.get("ProfitLossOnTradeInBaseCurrency", 0.0) or 0.0),
                pnl_fx_conversion_base=float(
                    cp.get("ProfitLossCurrencyConversion", 0.0) or 0.0),
                closed_pnl_instrument=float(cp.get("ClosedProfitLoss", 0.0) or 0.0),
                closed_pnl_base=float(
                    cp.get("ClosedProfitLossInBaseCurrency", 0.0) or 0.0),
                cost_opening_instrument=float(cp.get("CostOpening", 0.0) or 0.0),
                cost_closing_instrument=float(cp.get("CostClosing", 0.0) or 0.0),
                cost_opening_base=float(
                    cp.get("CostOpeningInBaseCurrency", 0.0) or 0.0),
                cost_closing_base=float(
                    cp.get("CostClosingInBaseCurrency", 0.0) or 0.0),
                closing_method=str(cp.get("ClosingMethod", "")),
                asset_type=str(cp.get("AssetType", "")),
                instrument_currency=str(daf.get("Currency", "")),
            ))
        return out

    def get_accounts(self) -> list[dict]:
        """全 sub-account 一覧 (Data 配列、raw dict)。

        See docs/api/saxo/endpoints.md#1-get-portv1accountsme
        """
        return self._api_get("/port/v1/accounts/me").get("Data", [])

    def get_trade_cost(self, *, account_key: str, uic: int, asset_type: str,
                       amount: float, price: float,
                       direction: str = "long") -> TradeCost:
        """指定銘柄・サイズの取引コスト見積りを意味的 snapshot で返す (ADR-029)。

        break-even 判定に使う。`result.total_cost_pct` が往復 break-even%、
        `result.break_even_price()` がコスト回収価格。

        **Amount と Price は必須** (どちらか欠けると Saxo は 400/404 を返す)。
        `direction` は "long"/"short"。応答に該当 side が無ければ SaxoAuthError。

        ADR-026 に基づき raw dict 露出を防ぐ。新規 field が必要な場合は `TradeCost`
        を拡張し docs/api/saxo/cost-fields.md に公式定義を追記 (citation 必須)。

        See docs/api/saxo/cost-fields.md
        """
        side_key = {"long": "Long", "short": "Short"}.get(direction)
        if side_key is None:
            raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")

        resp = self._api_get(
            f"/cs/v1/tradingconditions/cost/{account_key}/{uic}/{asset_type}"
            f"?Amount={amount}&Price={price}"
        )
        cost = resp.get("Cost", {})
        if side_key not in cost:
            raise SaxoAuthError(
                f"Cost response missing '{side_key}' side for Uic {uic} "
                f"(available: {list(cost.keys())}). "
                "Saxo API may have changed; verify docs/api/saxo/cost-fields.md"
            )
        side = cost[side_key]
        required = ("Currency", "TotalCost", "TotalCostPct", "TradingCost")
        missing = [k for k in required if k not in side]
        if missing:
            raise SaxoAuthError(
                f"Cost.{side_key} missing required fields {missing} for Uic {uic}. "
                "Saxo API may have changed; verify docs/api/saxo/cost-fields.md"
            )

        trading = side["TradingCost"]
        commissions = trading.get("Commissions") or [{}]
        comm = commissions[0]
        comm_rule = comm.get("Rule", {})
        conv = trading.get("ConversionCost", {})
        spread = trading.get("Spread", {})
        holding = side.get("HoldingCost", {})
        holding_total = sum(t.get("Value", 0.0) for t in holding.get("Tax", []))
        assumptions = resp.get("CostCalculationAssumptions", [])

        return TradeCost(
            instrument=resp.get("Instrument", str(uic)),  # see cost-fields.md#instrument
            uic=int(resp.get("Uic", uic)),
            asset_type=resp.get("AssetType", asset_type),
            direction=direction,
            amount=float(resp.get("Amount", amount)),
            price=float(resp.get("Price", price)),
            account_currency=resp.get("AccountCurrency", ""),  # see #accountcurrency
            instrument_currency=side["Currency"],  # see #cost-currency
            total_cost=float(side["TotalCost"]),  # see #totalcost
            total_cost_pct=float(side["TotalCostPct"]),  # see #totalcostpct
            is_round_trip="IncludesOpenAndCloseCost" in assumptions,  # see #costcalculationassumptions
            commission=float(comm.get("Value", 0.0)),  # see #commissions
            commission_pct=float(comm.get("Pct", 0.0)),
            min_commission=float(comm_rule.get("MinCommission", 0.0)),
            conversion_cost=float(conv.get("Value", 0.0)),  # see #conversioncost
            conversion_cost_pct=float(conv.get("Pct", 0.0)),
            conversion_rate_pct=float(conv.get("Rule", {}).get("Pct", 0.0)),
            spread_cost=float(spread.get("Value", 0.0)),  # see #spread
            spread_pct=float(spread.get("Pct", 0.0)),
            holding_cost=float(holding_total),  # see #holdingcost
            assumptions=assumptions,
        )

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

    # ADR-030: 買売を表す TradeEventType → side のマップ。
    # Direction field は "None" を返すため使えない (trade-report-fields.md)。
    _TRADE_EVENT_SIDE = {"Bought": "buy", "Sold": "sell"}

    def get_trade_reports(self, *, client_key: str, from_date: str, to_date: str,
                          account_key: Optional[str] = None) -> list[TradeReport]:
        """期間内の実約定 (fill) を意味的 snapshot のリストで返す (ADR-030)。

        執行事実層 `account_transactions` の供給源。`from_date`/`to_date` は
        "YYYY-MM-DD"。買売は `TradeEventType` から決定する (`Direction` は "None"
        を返すため使わない)。ADR-026 に基づき raw dict 露出を防ぐ。新規 field が
        必要な場合は `TradeReport` を拡張し docs/api/saxo/trade-report-fields.md に
        公式/観測定義を追記する。

        See docs/api/saxo/trade-report-fields.md
        """
        path = (f"/cs/v1/reports/trades/{client_key}"
                f"?FromDate={from_date}&ToDate={to_date}")
        if account_key:
            path += f"&AccountKey={account_key}"
        rows = self._api_get(path).get("Data", [])

        required = (
            "TradeId", "OrderId", "AccountId", "Uic", "InstrumentSymbol",
            "AssetType", "Amount", "Price", "TradeEventType", "TradeDate",
            "ValueDate", "TradeExecutionTime", "BookedAmountUSD",
            "BookedAmountAccountCurrency", "AccountCurrency",
        )
        reports: list[TradeReport] = []
        for r in rows:
            missing = [k for k in required if k not in r]
            if missing:
                raise SaxoAuthError(
                    f"trades report row missing required fields {missing} "
                    f"(TradeId={r.get('TradeId')}). "
                    "Saxo API may have changed; verify docs/api/saxo/trade-report-fields.md"
                )
            event = r["TradeEventType"]
            side = self._TRADE_EVENT_SIDE.get(event)
            if side is None:
                raise SaxoAuthError(
                    f"Unknown TradeEventType {event!r} (TradeId={r['TradeId']}). "
                    "Expected 'Bought'/'Sold'; verify docs/api/saxo/trade-report-fields.md"
                )
            amount = float(r["Amount"])
            reports.append(TradeReport(
                trade_id=str(r["TradeId"]),  # see trade-report-fields.md
                order_id=str(r["OrderId"]),  # broker_ref 結合キー
                account_id=r["AccountId"],
                side=side,                    # TradeEventType 由来
                quantity=abs(amount),
                amount_signed=amount,         # 正=買, 負=売
                price=float(r["Price"]),
                trade_date=date.fromisoformat(r["TradeDate"][:10]),
                value_date=date.fromisoformat(r["ValueDate"][:10]),  # settlement
                execution_time_utc=r["TradeExecutionTime"],
                booked_amount_usd=float(r["BookedAmountUSD"]),
                booked_amount_account_currency=float(r["BookedAmountAccountCurrency"]),
                account_currency=r["AccountCurrency"],
                instrument_symbol=r["InstrumentSymbol"],
                uic=int(r["Uic"]),
                asset_type=r["AssetType"],
                spread_cost_usd=float(r.get("SpreadCostUSD", 0.0)),
            ))
        return reports

    def get_bookings(self, *, client_key: str, from_date: str, to_date: str,
                     account_key: Optional[str] = None) -> list[CashBooking]:
        """期間内の**現金移動** (deposit/withdrawal) を意味的 snapshot で返す (ADR-030 Phase 5)。

        `GET /cs/v1/reports/bookings/{ClientKey}` は記帳全エントリ (約定内訳 + 現金移動 +
        手数料内訳) を返す。本メソッドは **`AssetType='Cash'` の行のみ**を抽出する
        (ETF 行は約定内訳で reports/trades と二重計上になるため除外)。`from_date`/
        `to_date` は "YYYY-MM-DD"。向き (deposit/withdrawal) は `AmountUSD` の符号で
        判定する (写像は account_ledger 側)。ADR-026 に基づき raw dict 露出を防ぐ。

        See docs/api/saxo/booking-fields.md
        """
        path = (f"/cs/v1/reports/bookings/{client_key}"
                f"?FromDate={from_date}&ToDate={to_date}")
        if account_key:
            path += f"&AccountKey={account_key}"
        rows = self._api_get(path).get("Data", [])

        required = (
            "BkAmountId", "AccountId", "Date", "ValueDate", "AmountUSD",
            "AmountAccountCurrency", "AccountCurrency", "InstrumentSymbol",
        )
        bookings: list[CashBooking] = []
        for r in rows:
            if r.get("AssetType") != "Cash":
                continue
            missing = [k for k in required if k not in r]
            if missing:
                raise SaxoAuthError(
                    f"bookings (Cash) row missing required fields {missing} "
                    f"(BkAmountId={r.get('BkAmountId')}). "
                    "Saxo API may have changed; verify docs/api/saxo/booking-fields.md"
                )
            bookings.append(CashBooking(
                booking_id=str(r["BkAmountId"]),       # see booking-fields.md
                account_id=r["AccountId"],
                date=date.fromisoformat(r["Date"][:10]),
                value_date=date.fromisoformat(r["ValueDate"][:10]),  # settlement
                amount_usd=float(r["AmountUSD"]),       # 符号付: + = cash in
                amount_account_currency=float(r["AmountAccountCurrency"]),
                account_currency=r["AccountCurrency"],
                symbol=r["InstrumentSymbol"],           # 例 CASHINTRTP (口座間振替)
                description=r.get("InstrumentDescription", ""),
            ))
        return bookings

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
