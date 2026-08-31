"""ADR-035: live 読み取り(Saxo/realtime)を型付き JSON payload に整形する層。

MCP サーバ(`src/mcp_saxo.py`)から呼ばれる純粋・テスト可能な関数群。duckdb ファイルに
無い live 読み取り(残高/建玉/注文/コスト/realtime)を担う。蓄積層 SQL は既存 duckdb MCP。

構成:
- **serializers**: dataclass → named-field dict。raw dict を露出しない(ADR-026)。
  「`price` か `price_per_unit` か」を Claude に推測させない唯一の正本。
- **decide_mode / _retry_on_lock / read_live**: 接続規律(ADR-025/035)。access が有効なら
  read_only で足りる(get_access_token は書き込まない)。buffer 内/失効なら refresh の
  書き込みが要るため read_write に昇格。refresh も失効なら AuthRequired。DuckDB は単一
  writer でロック競合しうるため、connect を指数バックオフでリトライする。
- **payload 関数**: 各ツールが返す最終 dict。AuthRequired を構造化エラーへ変換する。
"""
from __future__ import annotations

import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import duckdb

from src.db import SenseiDB, now_jst
from src.realtime import fetch_realtime_quote
from src.saxo_client import (
    ACCESS_TOKEN_REFRESH_BUFFER_SEC,
    PROVIDER,
    SAXO_UIC,
    AccountBalance,
    LivePosition,
    OpenOrder,
    SaxoAuthError,
    SaxoClient,
    SaxoConfig,
    TradeCost,
)

DB_PATH = Path(__file__).parent.parent / "data" / "sensei.duckdb"

# 主取引口座(円口座, SOXL 建玉を持つ)。従来 entry-analysis 等の prose に散在していた
# ハードコードを ADR-035 で1箇所へ集約。将来は「約定履歴を持つ口座」の動的選択へ(Issue #12)。
MAIN_ACCOUNT_ID = "77800/T126816"


class AuthRequired(Exception):
    """Saxo refresh token 失効。会話層で saxo_oauth_init を起動する必要(ADR-025/035)。

    MCP はブラウザ認証を起動しない(人間のログインが要るため)。ツールはこれを
    構造化エラー(`_auth_error`)へ変換し、Claude が再認証フローへ誘導する。
    """


# ────────────────────────────── serializers (ADR-026) ──────────────────────────────

def balance_to_dict(b: AccountBalance) -> dict:
    """口座残高。sizing は `spending_power`(`settled_cash_balance` は未決済除外で不可)。"""
    return {
        "account_id": b.account_id,
        "account_key": b.account_key,
        "currency": b.currency,
        "spending_power": b.spending_power,
        "cash_available_for_trading": b.cash_available_for_trading,
        "settled_cash_balance": b.settled_cash_balance,
        "total_value": b.total_value,
        "unrealized_pnl": b.unrealized_pnl,
        "transactions_not_booked": b.transactions_not_booked,
        "open_positions_count": b.open_positions_count,
        "net_positions_count": b.net_positions_count,
        "non_margin_positions_value": b.non_margin_positions_value,
        "calculation_reliability": b.calculation_reliability,
    }


def position_to_dict(p: LivePosition) -> dict:
    """ライブ建玉。`amount` は符号付き net 数量(正=long/負=short)。"""
    return {
        "account_id": p.account_id,
        "uic": p.uic,
        "symbol": p.symbol,
        "amount": p.amount,
        "open_price": p.open_price,
        "unrealized_pnl_base": p.unrealized_pnl_base,
    }


def order_to_dict(o: OpenOrder) -> dict:
    """ライブ未約定注文。`order_id` は trades.broker_ref との結合キー。`price` は Market で None。"""
    return {
        "order_id": o.order_id,
        "account_id": o.account_id,
        "uic": o.uic,
        "symbol": o.symbol,
        "amount": o.amount,
        "buy_sell": o.buy_sell,
        "order_type": o.order_type,
        "price": o.price,
        "status": o.status,
    }


def trade_cost_to_dict(tc: TradeCost) -> dict:
    """往復取引コスト。`total_cost_pct` が break-even 値幅%、`break_even_price` は回収価格。"""
    return {
        "instrument": tc.instrument,
        "uic": tc.uic,
        "asset_type": tc.asset_type,
        "direction": tc.direction,
        "amount": tc.amount,
        "price": tc.price,
        "account_currency": tc.account_currency,
        "instrument_currency": tc.instrument_currency,
        "total_cost": tc.total_cost,
        "total_cost_pct": tc.total_cost_pct,
        "is_round_trip": tc.is_round_trip,
        "commission": tc.commission,
        "commission_pct": tc.commission_pct,
        "min_commission": tc.min_commission,
        "conversion_cost": tc.conversion_cost,
        "conversion_cost_pct": tc.conversion_cost_pct,
        "conversion_rate_pct": tc.conversion_rate_pct,
        "spread_cost": tc.spread_cost,
        "spread_pct": tc.spread_pct,
        "holding_cost": tc.holding_cost,
        "assumptions": list(tc.assumptions),
        "break_even_price": tc.break_even_price(),
    }


def quote_to_dict(q) -> dict:
    """延長時間の現値。datetime は JSON 化のため isoformat。`is_thin` は sizing 注記(ADR-031)。

    `regular_close_date` / `baseline_stale_days` を必ず含める。乖離%は現値と基準終値の
    関係なので、基準がいつのものか分からないまま `delta_pct` だけ読むと古い終値との差を
    現値の動きと誤読する。基準が stale の時 `delta_pct` は None になる (ADR-031)。
    """
    return {
        "symbol": q.symbol,
        "price": q.price,
        "fetched_at": q.fetched_at.isoformat(),
        "bar_time_et": q.bar_time_et.isoformat(),
        "regular_close": q.regular_close,
        "regular_close_date": q.regular_close_date.isoformat(),
        "baseline_stale_days": q.baseline_stale_days,
        "delta_pct": q.delta_pct,
        "session": q.session,
        "source": q.source,
        "confirm_source": q.confirm_source,
        "confirm_price": q.confirm_price,
        "is_thin": q.is_thin,
        "summary": q.summary(),
    }


# ─────────────────────────── 接続規律 (ADR-025 / ADR-035) ───────────────────────────

def decide_mode(
    access: Optional[dict], refresh: Optional[dict], now: datetime
) -> str:
    """必要な DB 接続モードを決める純関数。

    - access に buffer(`ACCESS_TOKEN_REFRESH_BUFFER_SEC`)があれば `read_only`
      (`get_access_token` は書き込まず、duckdb MCP と共存できる)。
    - access が buffer 内/不在でも refresh が有効なら、refresh で token を書くため
      `read_write`。
    - refresh も無ければ `auth_required`。

    access/refresh は `SenseiDB.get_active_token`(expires_at>now かつ未 revoke で
    フィルタ済)の戻り値 or None。
    """
    if access is not None:
        remaining = (access["expires_at"] - now).total_seconds()
        if remaining > ACCESS_TOKEN_REFRESH_BUFFER_SEC:
            return "read_only"
    if refresh is not None:
        return "read_write"
    return "auth_required"


def _retry_on_lock(
    thunk: Callable[[], object], *, sleep, attempts: int, base_backoff: float
):
    """DuckDB のロック競合(`IOException`)を指数バックオフでリトライする。

    keepalive/scripts が RW を短時間保持する瞬間に connect が弾かれうるため。
    最終試行でも失敗したら最後の例外を送出する。
    """
    last: Optional[BaseException] = None
    for i in range(attempts):
        try:
            return thunk()
        except duckdb.IOException as exc:
            last = exc
            if i < attempts - 1:
                sleep(base_backoff * (2 ** i))
    assert last is not None
    raise last


def read_live(
    op: Callable[[SaxoClient], object],
    *,
    environment: Optional[str] = None,
    db_path: Path | str = DB_PATH,
    config: Optional[SaxoConfig] = None,
    connect=duckdb.connect,
    sleep=time.sleep,
    now=now_jst,
    attempts: int = 4,
    base_backoff: float = 0.2,
):
    """短命 DB 接続で `SaxoClient` を組み、`op(client)` を実行して結果を返す(ADR-035)。

    access が有効なら read_only、失効時のみ read_write に昇格して on-demand refresh
    (書き込み)する。refresh 失効時は `AuthRequired`。接続はアイドル中に保持しない
    (`closing` で即閉じる、ADR-025)。ロック競合はバックオフでリトライする。
    """
    cfg = config or SaxoConfig.from_env(environment=environment)
    env = cfg.environment

    if not Path(db_path).exists():
        raise AuthRequired(
            f"Saxo 認証 DB が見つかりません({db_path})。"
            "scripts/saxo_oauth_init.py で認証してください(ADR-025)。"
        )

    def _probe_mode():
        with closing(connect(str(db_path), read_only=True)) as conn:
            db = SenseiDB(conn, init_schema=False)
            access = db.get_active_token(PROVIDER, env, "access")
            refresh = db.get_active_token(PROVIDER, env, "refresh")
            return decide_mode(access, refresh, now())

    mode = _retry_on_lock(
        _probe_mode, sleep=sleep, attempts=attempts, base_backoff=base_backoff
    )
    if mode == "auth_required":
        raise AuthRequired(
            "有効な Saxo refresh token がありません。"
            "scripts/saxo_oauth_init.py で再認証してください(ADR-025)。"
        )
    read_only = mode == "read_only"

    def _run():
        with closing(connect(str(db_path), read_only=read_only)) as conn:
            db = SenseiDB(conn, init_schema=False)
            client = SaxoClient(db, config=cfg)
            client.get_access_token()  # read_write 時はここで on-demand refresh(書き込み)
            return op(client)

    return _retry_on_lock(
        _run, sleep=sleep, attempts=attempts, base_backoff=base_backoff
    )


# ─────────────────────────────── payload 関数 ───────────────────────────────

def _auth_error(exc: Exception) -> dict:
    return {
        "error": "AUTH_REQUIRED",
        "message": str(exc),
        "remedy": (
            "会話層で scripts/saxo_oauth_init.py をバックグラウンド起動して再認証"
            "してください(ブラウザログインのみ人間が担当、ADR-025)。"
        ),
    }


def _resolve_account_key(client: SaxoClient, account_id: str) -> str:
    """account_id(例 '77800/T126816') → AccountKey を /accounts/me から解決する。"""
    for a in client.get_accounts():
        if a.get("AccountId") == account_id:
            return a["AccountKey"]
    raise SaxoAuthError(f"Account {account_id} が /accounts/me に見つかりません")


def account_balances() -> dict:
    """全 active 口座の残高(sizing は spending_power)。"""
    try:
        bals = read_live(lambda c: c.get_all_account_balances())
    except AuthRequired as exc:
        return _auth_error(exc)
    return {"accounts": [balance_to_dict(b) for b in bals]}


def positions() -> dict:
    """ライブ建玉(net 数量)。"""
    try:
        ps = read_live(lambda c: c.get_live_positions())
    except AuthRequired as exc:
        return _auth_error(exc)
    return {"positions": [position_to_dict(p) for p in ps]}


def open_orders() -> dict:
    """ライブ未約定注文(OCO 脚含む)。"""
    try:
        os_ = read_live(lambda c: c.get_open_orders())
    except AuthRequired as exc:
        return _auth_error(exc)
    return {"orders": [order_to_dict(o) for o in os_]}


def trade_cost(
    symbol: str, amount: float, price: float, direction: str = "long",
    account_id: str = MAIN_ACCOUNT_ID,
) -> dict:
    """指定銘柄・サイズの往復取引コスト/break-even を返す(ADR-029)。"""
    if symbol not in SAXO_UIC:
        return {
            "error": "UNKNOWN_SYMBOL",
            "message": (
                f"{symbol} は SAXO_UIC 未登録。/ref/v1/instruments で UIC を解決し "
                "src.saxo_client.SAXO_UIC に追加してください(docs/api/saxo)。"
            ),
        }
    uic, asset_type = SAXO_UIC[symbol]

    def op(c: SaxoClient):
        account_key = _resolve_account_key(c, account_id)
        return c.get_trade_cost(
            account_key=account_key, uic=uic, asset_type=asset_type,
            amount=amount, price=price, direction=direction,
        )

    try:
        tc = read_live(op)
    except AuthRequired as exc:
        return _auth_error(exc)
    return trade_cost_to_dict(tc)


def realtime_quote(symbol: str) -> dict:
    """延長時間の現値(yfinance 主 + Tiingo 裏取り)。Saxo/DB 不要(ADR-031)。"""
    try:
        q = fetch_realtime_quote(symbol)
    except RuntimeError as exc:  # parquet 日足が空(FX 等 realtime universe 外)
        return {"error": "NO_BASELINE", "message": str(exc)}
    return quote_to_dict(q)
