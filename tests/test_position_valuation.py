"""src/position.py の評価ロジック (I/O なし) のテスト。

FIFO の畳み込みは tests/test_ledger_positions.py が SQL 経由で通しているので、
ここは現値評価と表示の不変条件だけを見る:
  - 含み損益は取得原価基準 (price_per_unit 基準ではない)
  - % はドル額と必ず併記される (CLAUDE.md Rules)
  - 評価値には出所ラベルが必ず付く (ADR-031: 終値と現値を取り違えない)
"""
from __future__ import annotations

from datetime import date

import pytest

from src.position import (
    LedgerFill,
    LedgerPosition,
    fifo_open_lots,
    format_valuation,
    value_position,
)


def _position(quantity=25.0, cost_usd=3004.84) -> LedgerPosition:
    return LedgerPosition(
        instrument="SOXL",
        quantity=quantity,
        cost_usd=cost_usd,
        avg_price=cost_usd / quantity,
        opened_on=date(2026, 8, 20),
    )


class TestValuePosition:
    def test_loss_is_measured_against_cost_basis(self):
        """含み損益は手数料込みの原価基準。25株 * 115.76 - 3004.84 = -110.84。"""
        v = value_position(_position(), mark=115.76, mark_label="9/10終値")

        assert v.market_value_usd == pytest.approx(2894.00)
        assert v.pnl_usd == pytest.approx(-110.84)
        assert v.pnl_pct == pytest.approx(-3.688, abs=1e-3)

    def test_gain_is_positive(self):
        v = value_position(_position(), mark=125.87, mark_label="9/9終値")

        assert v.pnl_usd == pytest.approx(141.91)
        assert v.pnl_pct > 0

    def test_commission_makes_breakeven_higher_than_fill_price(self):
        """約定単価 119.879 で評価しても、手数料ぶんまだ損。

        建値を price_per_unit で持つと、この価格で「トントン」と誤判定する。
        """
        v = value_position(_position(), mark=119.879, mark_label="test")

        assert v.pnl_usd < 0
        assert v.pnl_usd == pytest.approx(-7.865, abs=1e-3)

    def test_mark_label_is_required(self):
        """出所の無い評価値は作らせない (stale な終値を現値と読み違えるため)。"""
        with pytest.raises(ValueError, match="mark_label"):
            value_position(_position(), mark=115.76, mark_label="")


class TestFormatValuation:
    def test_line_carries_both_dollar_and_percent(self):
        line = format_valuation(
            value_position(_position(), mark=115.76, mark_label="9/10終値")
        )

        assert "$110.84" in line
        assert "3.69%" in line
        assert "9/10終値" in line

    def test_negative_pnl_is_signed_once(self):
        """マイナスは符号を1つだけ出す ($-110.84 や --3.69% にしない)。"""
        line = format_valuation(
            value_position(_position(), mark=115.76, mark_label="9/10終値")
        )

        assert "-$110.84" in line
        assert "$-" not in line
        assert "--" not in line

    def test_positive_pnl_is_marked_with_plus(self):
        line = format_valuation(
            value_position(_position(), mark=125.87, mark_label="9/9終値")
        )

        assert "+$141.91" in line
        assert "+4.72%" in line

    def test_note_is_appended_when_given(self):
        line = format_valuation(
            value_position(_position(), mark=118.10, mark_label="pre"),
            note="⚠薄商い",
        )

        assert line.endswith("⚠薄商い")


class TestFifoEdgeCases:
    """SQL を通さない境界。台帳の取り込み漏れで在庫を超える売りが来た場合。"""

    def _fill(self, side, qty, amount, day):
        return LedgerFill(
            instrument="SOXL", side=side, quantity=qty, amount=amount,
            trade_date=date(2026, 8, day),
        )

    def test_oversell_does_not_produce_negative_position(self):
        """在庫を超える売りで残数量を負にしない (持っていないものを表示しない)。"""
        positions = fifo_open_lots([
            self._fill("buy", 3.0, -300.0, 18),
            self._fill("sell", 5.0, 550.0, 19),
        ])

        assert positions == {}

    def test_buy_after_oversell_is_not_cancelled_retroactively(self):
        """売り超過ぶんを繰り越して後続の買いから引かない。

        繰り越すと、取り込み漏れが1件あるだけで以後の建玉が消える。数量不整合の
        検出は reconcile_positions の責務で、評価側は見えている lot を素直に出す。
        """
        positions = fifo_open_lots([
            self._fill("sell", 5.0, 550.0, 18),
            self._fill("buy", 3.0, -300.0, 19),
        ])

        assert positions["SOXL"].quantity == pytest.approx(3.0)

    def test_empty_input_is_empty_result(self):
        assert fifo_open_lots([]) == {}
