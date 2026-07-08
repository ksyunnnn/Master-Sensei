"""mcp_saxo (ADR-035) の登録・委譲テスト。

薄い glue なので検証は最小: (1)5ツールが正しい名前で登録される、(2)各ツールが
live_reads の対応 payload 関数へ委譲する。behavior 本体は test_live_reads.py。
"""
from __future__ import annotations

from src import live_reads, mcp_saxo

EXPECTED_TOOLS = {
    "get_account_balances", "get_positions", "get_open_orders",
    "get_trade_cost", "get_realtime_quote",
}


def test_all_tools_registered():
    names = {t.name for t in mcp_saxo.mcp._tool_manager.list_tools()}
    assert EXPECTED_TOOLS <= names


def test_tools_have_descriptions():
    for t in mcp_saxo.mcp._tool_manager.list_tools():
        if t.name in EXPECTED_TOOLS:
            assert t.description, f"{t.name} に description が無い"


def test_get_account_balances_delegates(monkeypatch):
    monkeypatch.setattr(live_reads, "account_balances", lambda: {"accounts": []})
    assert mcp_saxo.get_account_balances() == {"accounts": []}


def test_get_positions_delegates(monkeypatch):
    monkeypatch.setattr(live_reads, "positions", lambda: {"positions": [{"symbol": "SOXL"}]})
    assert mcp_saxo.get_positions()["positions"][0]["symbol"] == "SOXL"


def test_get_trade_cost_passes_args(monkeypatch):
    seen = {}

    def fake(symbol, *, amount, price, direction):
        seen.update(symbol=symbol, amount=amount, price=price, direction=direction)
        return {"ok": True}

    monkeypatch.setattr(live_reads, "trade_cost", fake)
    mcp_saxo.get_trade_cost("SOXL", amount=10, price=200.0, direction="long")
    assert seen == {"symbol": "SOXL", "amount": 10, "price": 200.0, "direction": "long"}


def test_get_realtime_quote_delegates(monkeypatch):
    monkeypatch.setattr(live_reads, "realtime_quote", lambda s: {"symbol": s, "price": 1.0})
    assert mcp_saxo.get_realtime_quote("SOXL")["symbol"] == "SOXL"
