"""ADR-035: live 読み取り用 MCP サーバ(型付き Saxo/realtime アクセサ)。

既存 `SaxoClient`/`realtime` を JSON schema 付き MCP ツールとして公開し、Claude が
ad-hoc python でアクセサ名・パス・カラムを推測する往復を根絶する(ADR-026 の強制版)。
duckdb ファイルに無い **live 読み取り**(残高/建玉/注文/コスト/realtime)に限定する。
蓄積層(events/predictions/knowledge/trades…)の SQL 照会は既存 duckdb MCP の担当。

behavior 本体は `src/live_reads.py`(純粋・テスト可能)。本ファイルはそれを MCP ツール
として登録するだけの薄い glue。stdio transport で起動する(`.mcp.json` から)。

実行: python src/mcp_saxo.py   (cwd=リポジトリルート)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from src import live_reads

mcp = FastMCP("master-sensei-live")


@mcp.tool()
def get_account_balances() -> dict:
    """全 active 口座の残高 snapshot。

    sizing には `spending_power` を使う(`settled_cash_balance` は未決済を含まず
    過小評価のため使わない、ADR-026/028)。認証失効時は {"error":"AUTH_REQUIRED"} を返す。
    """
    return live_reads.account_balances()


@mcp.tool()
def get_positions() -> dict:
    """ライブ open 建玉。`amount` は符号付き net 数量(正=long/負=short)。"""
    return live_reads.positions()


@mcp.tool()
def get_open_orders() -> dict:
    """ライブ未約定注文(OCO 保護脚を含む)。`order_id` は trades.broker_ref との結合キー。"""
    return live_reads.open_orders()


@mcp.tool()
def get_trade_cost(
    symbol: str, amount: float, price: float, direction: str = "long"
) -> dict:
    """指定銘柄・サイズの往復取引コストと break-even(ADR-029)。

    `total_cost_pct` が break-even 値幅%、`break_even_price` が回収価格。
    symbol は SAXO_UIC 登録銘柄(現状 SOXL)。direction は "long"/"short"。
    """
    return live_reads.trade_cost(symbol, amount=amount, price=price, direction=direction)


@mcp.tool()
def get_realtime_quote(symbol: str) -> dict:
    """延長時間(pre/post 含む)の現値。yfinance 主 + Tiingo 裏取り(ADR-031)。

    `is_thin=True` の瞬間値は stop/エントリー基準にしない。FX 等 realtime universe 外は
    {"error":"NO_BASELINE"} を返す。
    """
    return live_reads.realtime_quote(symbol)


if __name__ == "__main__":
    mcp.run(transport="stdio")
