"""sync_saxo の break 分類ロジックのテスト (ADR-030)。

reconcile の数量差 (trades申告 vs 台帳実態) を ADR-030 の遷移カテゴリへ正しく
振り分けることを検証する。窓/マージは test_account_ledger.py 側で検証済み。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "sync_saxo", Path(__file__).parent.parent / "scripts" / "sync_saxo.py"
)
sync_saxo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_saxo)
_classify_break = sync_saxo._classify_break


def test_closed_but_still_open():
    """建玉申告あり・台帳 net=0 → クローズ済未反映。"""
    msg = _classify_break({"instrument": "SOXL", "trades_open_qty": 10, "ledger_net_qty": 0})
    assert "クローズ済未反映" in msg
    assert "SOXL" in msg


def test_unrecorded_entry():
    """申告ゼロ・台帳 net>0 → 未記録エントリー。"""
    msg = _classify_break({"instrument": "SOXL", "trades_open_qty": 0, "ledger_net_qty": 5})
    assert "未記録エントリー" in msg


def test_quantity_mismatch():
    """両方非ゼロで不一致 → 数量不一致 (注文改定/部分約定)。"""
    msg = _classify_break({"instrument": "SOXL", "trades_open_qty": 10, "ledger_net_qty": 7})
    assert "数量不一致" in msg


def test_both_zero():
    """両方ゼロ (理論上は break にならないが防御的に分類)。"""
    msg = _classify_break({"instrument": "SOXL", "trades_open_qty": 0, "ledger_net_qty": 0})
    assert "両建てゼロ" in msg


def test_exit_codes_distinct():
    """OK / BREAKS / AUTH は別コード (呼び出し側が分岐できる)。"""
    assert len({sync_saxo.EXIT_OK, sync_saxo.EXIT_BREAKS, sync_saxo.EXIT_AUTH}) == 3


# ── 3層照合の追加 (ADR-030): live建玉/注文の分類と escalation ──

from types import SimpleNamespace
from unittest.mock import MagicMock


def test_net_by_symbol_aggregates_and_drops_zero():
    """同一 symbol を合算し、相殺で 0 になった建玉は落とす。"""
    positions = [
        SimpleNamespace(symbol="SOXL", amount=5.0),
        SimpleNamespace(symbol="SOXL", amount=3.0),
        SimpleNamespace(symbol="SOXS", amount=2.0),
        SimpleNamespace(symbol="SOXS", amount=-2.0),  # 相殺 → 除外
    ]
    assert sync_saxo._net_by_symbol(positions) == {"SOXL": 8.0}


def test_classify_live_break_ledger_undershoots():
    """ライブ>台帳 → 台帳の取りこぼし。"""
    msg = sync_saxo._classify_live_break(
        {"instrument": "SOXL", "live_net_qty": 8, "ledger_net_qty": 5})
    assert "取りこぼし" in msg


def test_classify_live_break_ledger_extra():
    """ライブ<台帳 → 台帳に余分。"""
    msg = sync_saxo._classify_live_break(
        {"instrument": "SOXL", "live_net_qty": 0, "ledger_net_qty": 3})
    assert "余分" in msg


def test_classify_order_break_live_only():
    msg = sync_saxo._classify_order_break({"order_id": "999", "side": "live_only"})
    assert "未記録" in msg


def test_classify_order_break_trades_only():
    msg = sync_saxo._classify_order_break(
        {"order_id": "5409497457", "side": "trades_only",
         "instrument": "SOXL", "quantity": 5})
    assert "ライブに無し" in msg


def test_classify_order_break_placed_no_ref():
    msg = sync_saxo._classify_order_break(
        {"order_id": None, "side": "placed_no_ref", "instrument": "SOXL", "quantity": 5})
    assert "broker_ref 未設定" in msg


def test_escalation_stops_when_resolved():
    """live≠台帳 を最初の窓拡大で解消 → 全年 mirror まで行かない。"""
    db = MagicMock()
    # 1回目=break, 2回目(30d 再mirror後)=解消
    db.reconcile_live_positions.side_effect = [
        [{"instrument": "SOXL", "live_net_qty": 8, "ledger_net_qty": 5}],
        [],
    ]
    client = MagicMock()
    client.get_trade_reports.return_value = []
    client.get_bookings.return_value = []
    client.get_accounts.return_value = [{"ClientKey": "C1"}]
    breaks = sync_saxo._reconcile_live_with_escalation(
        db, client, {"SOXL": 8.0}, "2026-06-29", full=False)
    assert breaks == []
    assert db.reconcile_live_positions.call_count == 2  # 全年まで行かず2回で解決


def test_escalation_skipped_when_full():
    """既に全年 mirror 済み (full=True) なら escalation せず1回照合のみ。"""
    db = MagicMock()
    db.reconcile_live_positions.return_value = [
        {"instrument": "SOXL", "live_net_qty": 8, "ledger_net_qty": 5}]
    client = MagicMock()
    breaks = sync_saxo._reconcile_live_with_escalation(
        db, client, {"SOXL": 8.0}, "2026-06-29", full=True)
    assert len(breaks) == 1
    assert db.reconcile_live_positions.call_count == 1
