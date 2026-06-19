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
