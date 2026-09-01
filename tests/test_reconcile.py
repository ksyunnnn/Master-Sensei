"""ポジション照合 reconcile_positions のテスト (ADR-030 Phase4)。

判断層 trades が申告する保有ポジション vs 執行事実層 account_transactions(Parquet)
の純ポジションを突合し、乖離(break)を検出する。これが「DBがよくずれる」の機械検出。
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from src.account_ledger import (
    explain_ledger_surplus_by_closed_positions,
    write_transactions_parquet,
)
from src.db import SenseiDB
from src.saxo_client import ClosedPosition, TradeReport
from src.account_ledger import trade_reports_to_rows


@pytest.fixture
def db(db_conn):
    return SenseiDB(db_conn)


def _ledger_row(instrument, side, qty, order_id, trade_id):
    return {
        "trade_date": date(2026, 6, 1), "settlement_date": date(2026, 6, 2),
        "type": side, "instrument": instrument, "quantity": qty,
        "price_per_unit": 100.0, "amount": -100.0 * qty if side == "buy" else 100.0 * qty,
        "currency": "USD", "fx_rate": 150.0, "amount_jpy": 1.0,
        "realized_pnl": None, "broker_ref": trade_id, "order_id": order_id,
        "account_id": "77800/T126816", "source": "test", "updated_at": datetime(2026, 6, 3),
    }


def test_no_break_when_ledger_matches_trades(db, tmp_path):
    """trades が closed、台帳も net 0 → 乖離なし。"""
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _ledger_row("SOXL", "buy", 3.0, "OA", "TA"),
        _ledger_row("SOXL", "sell", 3.0, "OB", "TB"),
    ], p)
    tid = db.add_trade(instrument="SOXL", direction="long",
                       entry_date=date(2026, 6, 1), entry_price=218.0, quantity=3,
                       broker_ref="OA")
    db.close_trade(tid, exit_date=date(2026, 6, 2), exit_price=243.0)
    breaks = db.reconcile_positions(str(p))
    assert breaks == []


def test_break_when_trades_claims_open_but_ledger_flat(db, tmp_path):
    """trades は filled かつ未手仕舞い(保有3株申告)、台帳は net 0 → break。

    これが今回の trade 12 ドリフト (クローズ済なのに建玉中) の検出。
    """
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _ledger_row("SOXL", "buy", 3.0, "OA", "TA"),
        _ledger_row("SOXL", "sell", 3.0, "OB", "TB"),
    ], p)
    db.add_trade(instrument="SOXL", direction="long",
                 entry_date=date(2026, 6, 1), entry_price=218.0, quantity=3,
                 status="filled", broker_ref="OA")  # exit_date なし = 建玉中申告
    breaks = db.reconcile_positions(str(p))
    assert len(breaks) == 1
    b = breaks[0]
    assert b["instrument"] == "SOXL"
    assert b["trades_open_qty"] == 3.0
    assert b["ledger_net_qty"] == 0.0


def test_break_when_ledger_position_unrecorded(db, tmp_path):
    """台帳に net 2株あるが trades に申告なし → 未記録エントリーの break。"""
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([
        _ledger_row("TQQQ", "buy", 2.0, "OC", "TC"),
    ], p)
    breaks = db.reconcile_positions(str(p))
    assert len(breaks) == 1
    assert breaks[0]["instrument"] == "TQQQ"
    assert breaks[0]["ledger_net_qty"] == 2.0
    assert breaks[0]["trades_open_qty"] == 0.0


def test_placed_trade_not_counted_as_open(db, tmp_path):
    """placed(未約定)は保有ポジションでない。台帳が空でも break にしない。"""
    p = tmp_path / "tx.parquet"
    write_transactions_parquet([], p)
    db.add_trade(instrument="SOXL", direction="long",
                 entry_date=date(2026, 6, 2), entry_price=228.0, quantity=5,
                 status="placed", broker_ref="5409497457")
    breaks = db.reconcile_positions(str(p))
    assert breaks == []


# ── reconcile_live_positions: ライブ建玉 ↔ 台帳 (mirror 漏れ検出, ADR-030) ──

class TestReconcileLivePositions:
    def test_no_break_when_live_matches_ledger(self, db, tmp_path):
        """ライブ建玉 8株 と台帳 net 8株 が一致 → break なし。"""
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([_ledger_row("SOXL", "buy", 8.0, "OA", "TA")], p)
        breaks = db.reconcile_live_positions({"SOXL": 8.0}, str(p))
        assert breaks == []

    def test_break_when_ledger_undershoots_live(self, db, tmp_path):
        """ライブ建玉8株あるのに台帳 net=5株 → mirror 漏れ (台帳の取りこぼし)。"""
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([_ledger_row("SOXL", "buy", 5.0, "OA", "TA")], p)
        breaks = db.reconcile_live_positions({"SOXL": 8.0}, str(p))
        assert len(breaks) == 1
        assert breaks[0]["instrument"] == "SOXL"
        assert breaks[0]["live_net_qty"] == 8.0
        assert breaks[0]["ledger_net_qty"] == 5.0

    def test_break_when_ledger_has_extra(self, db, tmp_path):
        """ライブはフラットだが台帳 net=3株 → 台帳に余分 (クローズ未mirror)。"""
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([_ledger_row("SOXL", "buy", 3.0, "OA", "TA")], p)
        breaks = db.reconcile_live_positions({}, str(p))
        assert len(breaks) == 1
        assert breaks[0]["live_net_qty"] == 0.0
        assert breaks[0]["ledger_net_qty"] == 3.0

    def test_no_break_when_both_flat(self, db, tmp_path):
        """ライブ0・台帳 net0 (buy+sell 相殺) → break なし。"""
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([
            _ledger_row("SOXL", "buy", 3.0, "OA", "TA"),
            _ledger_row("SOXL", "sell", 3.0, "OB", "TB"),
        ], p)
        breaks = db.reconcile_live_positions({}, str(p))
        assert breaks == []

    def test_missing_parquet_treated_as_empty_ledger(self, db, tmp_path):
        """台帳ファイルが無くてもライブ建玉があれば break として可視化する。"""
        breaks = db.reconcile_live_positions({"SOXL": 8.0}, str(tmp_path / "none.parquet"))
        assert len(breaks) == 1
        assert breaks[0]["ledger_net_qty"] == 0.0


# ── reconcile_open_orders: ライブ注文 ↔ trades placed (ADR-030) ──

class TestReconcileOpenOrders:
    def test_no_break_when_orders_match(self, db):
        """ライブ注文 OrderId とdb placed の broker_ref が一致 → break なし。"""
        db.add_trade(instrument="SOXL", direction="long",
                     entry_date=date(2026, 6, 2), entry_price=228.0, quantity=5,
                     status="placed", broker_ref="5409497457")
        breaks = db.reconcile_open_orders({"5409497457"})
        assert breaks == []

    def test_live_only_order(self, db):
        """ライブに注文があるが trades に未記録 → live_only。"""
        breaks = db.reconcile_open_orders({"999"})
        assert len(breaks) == 1
        assert breaks[0]["side"] == "live_only"
        assert breaks[0]["order_id"] == "999"

    def test_trades_only_order(self, db):
        """trades は placed だがライブに無い → trades_only (約定/失効/取消)。"""
        db.add_trade(instrument="SOXL", direction="long",
                     entry_date=date(2026, 6, 2), entry_price=228.0, quantity=5,
                     status="placed", broker_ref="5409497457")
        breaks = db.reconcile_open_orders(set())
        assert len(breaks) == 1
        assert breaks[0]["side"] == "trades_only"
        assert breaks[0]["order_id"] == "5409497457"
        assert breaks[0]["instrument"] == "SOXL"
        assert breaks[0]["quantity"] == 5.0

    def test_placed_without_broker_ref(self, db):
        """placed だが broker_ref 未設定 → 照合不能を placed_no_ref として報告。"""
        db.add_trade(instrument="SOXL", direction="long",
                     entry_date=date(2026, 6, 2), entry_price=228.0, quantity=5,
                     status="placed")
        breaks = db.reconcile_open_orders(set())
        assert len(breaks) == 1
        assert breaks[0]["side"] == "placed_no_ref"
        assert breaks[0]["order_id"] is None


def _closed_position(instrument="SOXL", amount=12.0, opening_side="Buy",
                     closing_position_id="C1"):
    """決済済ポジションの最小 fixture (数量と方向だけが照合に効く)。"""
    return ClosedPosition(
        unique_id=f"O1-{closing_position_id}", account_id="77800/T126816",
        uic=46780, symbol=instrument, amount=amount, opening_side=opening_side,
        open_price=134.13, closing_price=120.03,
        execution_time_open_utc="2026-08-18T13:30:00Z",
        execution_time_close_utc="2026-08-19T14:07:32Z",
        opening_position_id="O1", closing_position_id=closing_position_id,
        pnl_instrument=-169.2, pnl_base=-27082.6,
        pnl_fx_conversion_base=-2943.66,
        closed_pnl_instrument=-169.2, closed_pnl_base=-30026.26,
        cost_opening_instrument=-1.42, cost_closing_instrument=-1.3,
        cost_opening_base=-227.0, cost_closing_base=-206.0,
        closing_method="Fifo", asset_type="Etf", instrument_currency="USD",
    )


class TestExplainLedgerSurplusByClosedPositions:
    """booking 未着 (T+1) の決済を closedpositions で説明し、真の乖離と切り分ける。

    背景: 執行事実層の供給源 reports/trades は T+1 booking のため、決済当日は
    台帳に sell 行が入らない。その状態で「ライブ建玉=0 / 台帳net>0」を真の乖離と
    誤報するのを防ぐ (2026-08-19 SOXL 24株決済で実際に誤報した)。
    """

    def test_surplus_fully_explained_by_closed_positions(self):
        """ライブ0 / 台帳24 を 12株×2 の決済が過不足なく説明 → benign。"""
        breaks = [{"instrument": "SOXL", "live_net_qty": 0.0, "ledger_net_qty": 24.0}]
        closed = [_closed_position(amount=12.0, closing_position_id="C1"),
                  _closed_position(amount=12.0, closing_position_id="C2")]
        unexplained, explained = explain_ledger_surplus_by_closed_positions(
            breaks, closed)
        assert unexplained == []
        assert len(explained) == 1
        assert explained[0]["instrument"] == "SOXL"
        assert explained[0]["closed_qty"] == 24.0

    def test_no_closed_positions_leaves_break_unexplained(self):
        """決済が無ければ説明できない → 真の乖離として残す。"""
        breaks = [{"instrument": "SOXL", "live_net_qty": 0.0, "ledger_net_qty": 24.0}]
        unexplained, explained = explain_ledger_surplus_by_closed_positions(breaks, [])
        assert unexplained == breaks
        assert explained == []

    def test_partial_coverage_stays_unexplained(self):
        """数量が足りない説明は受け入れない (中途半端に消さず人間に見せる)。"""
        breaks = [{"instrument": "SOXL", "live_net_qty": 0.0, "ledger_net_qty": 24.0}]
        closed = [_closed_position(amount=12.0)]
        unexplained, explained = explain_ledger_surplus_by_closed_positions(
            breaks, closed)
        assert unexplained == breaks
        assert explained == []

    def test_other_instrument_does_not_explain(self):
        """別 instrument の決済で穴埋めしない。"""
        breaks = [{"instrument": "SOXL", "live_net_qty": 0.0, "ledger_net_qty": 24.0}]
        closed = [_closed_position(instrument="TQQQ", amount=24.0)]
        unexplained, explained = explain_ledger_surplus_by_closed_positions(
            breaks, closed)
        assert unexplained == breaks
        assert explained == []

    def test_ledger_shortfall_is_never_explained(self):
        """live > 台帳 (台帳の取りこぼし) は決済では説明できない → 残す。"""
        breaks = [{"instrument": "SOXL", "live_net_qty": 24.0, "ledger_net_qty": 0.0}]
        closed = [_closed_position(amount=24.0)]
        unexplained, explained = explain_ledger_surplus_by_closed_positions(
            breaks, closed)
        assert unexplained == breaks
        assert explained == []

    def test_short_close_explains_negative_ledger_surplus(self):
        """売り建ての決済は台帳 buy 行に対応し、台帳net が負の余剰を説明する。"""
        breaks = [{"instrument": "SOXL", "live_net_qty": 0.0, "ledger_net_qty": -12.0}]
        closed = [_closed_position(amount=12.0, opening_side="Sell")]
        unexplained, explained = explain_ledger_surplus_by_closed_positions(
            breaks, closed)
        assert unexplained == []
        assert len(explained) == 1

    def test_partially_reduced_position_explained(self):
        """24株のうち12株だけ決済しライブに12株残る場合も説明できる。"""
        breaks = [{"instrument": "SOXL", "live_net_qty": 12.0, "ledger_net_qty": 24.0}]
        closed = [_closed_position(amount=12.0)]
        unexplained, explained = explain_ledger_surplus_by_closed_positions(
            breaks, closed)
        assert unexplained == []
        assert len(explained) == 1

    def test_empty_breaks_returns_empty(self):
        unexplained, explained = explain_ledger_surplus_by_closed_positions(
            [], [_closed_position()])
        assert unexplained == []
        assert explained == []


class TestFindUnbookedClosures:
    """同日往復の死角 (issue#20): 3層すべてが 0 になり「差分なし」と誤報する。

    建てて同日に決済すると positions/me も orders/me も空、reports/trades は
    反映遅延で未計上 → 台帳 net も trades 申告も 0 で一致してしまう。
    closedpositions にだけ決済が現れるので、そこから未計上を名指しする。
    """

    def test_closure_absent_from_ledger_is_reported(self, db, tmp_path):
        """台帳に決済脚が無い → 未計上として報告する。"""
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([_ledger_row("SOXL", "buy", 12.0, "O1", "T1")], p)
        cp = _closed_position(amount=12.0)
        unbooked = db.find_unbooked_closures([cp], str(p))
        assert len(unbooked) == 1
        assert unbooked[0]["instrument"] == "SOXL"
        assert unbooked[0]["quantity"] == 12.0
        assert unbooked[0]["closing_price"] == 120.03

    def test_closure_present_in_ledger_is_not_reported(self, db, tmp_path):
        """台帳に一致する決済脚がある → 反映済みなので報告しない。"""
        p = tmp_path / "tx.parquet"
        row = _ledger_row("SOXL", "sell", 12.0, "O2", "T2")
        row["price_per_unit"] = 120.03
        write_transactions_parquet([row], p)
        cp = _closed_position(amount=12.0)
        assert db.find_unbooked_closures([cp], str(p)) == []

    def test_matching_requires_same_side(self, db, tmp_path):
        """数量・価格が同じでも side が違えば決済脚ではない。"""
        p = tmp_path / "tx.parquet"
        row = _ledger_row("SOXL", "buy", 12.0, "O3", "T3")
        row["price_per_unit"] = 120.03
        write_transactions_parquet([row], p)
        cp = _closed_position(amount=12.0)
        assert len(db.find_unbooked_closures([cp], str(p))) == 1

    def test_short_close_matches_buy_row(self, db, tmp_path):
        """売り建ての決済は台帳 buy 行に対応する。"""
        p = tmp_path / "tx.parquet"
        row = _ledger_row("SOXL", "buy", 12.0, "O4", "T4")
        row["price_per_unit"] = 120.03
        write_transactions_parquet([row], p)
        cp = _closed_position(amount=12.0, opening_side="Sell")
        assert db.find_unbooked_closures([cp], str(p)) == []

    def test_empty_inputs(self, db, tmp_path):
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([_ledger_row("SOXL", "buy", 1.0, "O5", "T5")], p)
        assert db.find_unbooked_closures([], str(p)) == []

    def test_missing_parquet_reports_all_as_unbooked(self, db, tmp_path):
        """台帳ファイルが無ければ全件未計上 (黙って空を返さない)。"""
        cp = _closed_position(amount=12.0)
        unbooked = db.find_unbooked_closures([cp], str(tmp_path / "absent.parquet"))
        assert len(unbooked) == 1


class TestProtectiveLegNotCountedAsPosition:
    """保護脚は建玉ではない (ADR-038)。

    OCO の決済逆指値が約定した事実を status='filled' で記録すると、
    exit_date が NULL のため reconcile_positions が存在しない建玉を申告してしまう
    (2026-08-19 の SOXL 決済で実際に詰んだ)。parent_trade_id を持つ行は除外する。
    """

    def test_filled_leg_is_excluded_from_open_claim(self, db, tmp_path):
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([
            _ledger_row("SOXL", "buy", 12.0, "O1", "T1"),
            _ledger_row("SOXL", "sell", 12.0, "O2", "T2"),
        ], p)
        parent = db.add_trade(
            instrument="SOXL", direction="long", entry_date=date(2026, 8, 17),
            entry_price=134.13, quantity=12, broker_ref="O1")
        db.close_trade(parent, exit_date=date(2026, 8, 19), exit_price=120.03)
        leg = db.add_trade(
            instrument="SOXL", direction="long", entry_date=date(2026, 8, 18),
            entry_price=120.0, quantity=12, broker_ref="O2",
            status="placed", parent_trade_id=parent)
        db.update_trade_status(leg, "filled")

        # 脚が filled + exit_date なし でも建玉として数えない
        assert db.reconcile_positions(str(p)) == []

    def test_leg_without_parent_still_counts(self, db, tmp_path):
        """parent_trade_id が無ければ従来どおり建玉として数える (退行防止)。"""
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([_ledger_row("SOXL", "buy", 12.0, "O1", "T1")], p)
        tid = db.add_trade(
            instrument="SOXL", direction="long", entry_date=date(2026, 8, 18),
            entry_price=120.0, quantity=12, broker_ref="OX")
        db.update_trade_status(tid, "filled")
        assert db.reconcile_positions(str(p)) == []  # trades 12 == ledger 12

    def test_set_trade_parent_validates(self, db):
        tid = db.add_trade(
            instrument="SOXL", direction="long", entry_date=date(2026, 8, 18),
            entry_price=120.0, quantity=12)
        with pytest.raises(ValueError, match="not found"):
            db.set_trade_parent(tid, 99999)
        with pytest.raises(ValueError, match="itself"):
            db.set_trade_parent(tid, tid)

    def test_set_trade_parent_links(self, db):
        parent = db.add_trade(
            instrument="SOXL", direction="long", entry_date=date(2026, 8, 17),
            entry_price=134.13, quantity=12)
        leg = db.add_trade(
            instrument="SOXL", direction="long", entry_date=date(2026, 8, 18),
            entry_price=120.0, quantity=12, status="placed")
        db.set_trade_parent(leg, parent)
        got = db.conn.execute(
            "SELECT parent_trade_id FROM trades WHERE id = ?", [leg]).fetchone()[0]
        assert got == parent


def _balance(account_id, currency, settled_cash):
    """AccountBalance の最小構築 (現金照合に使うのは3フィールドのみ)。"""
    from src.saxo_client import AccountBalance
    return AccountBalance(
        account_id=account_id, account_key="K", currency=currency,
        spending_power=settled_cash, cash_available_for_trading=settled_cash,
        settled_cash_balance=settled_cash, total_value=settled_cash,
        unrealized_positions_value=0.0, transactions_not_booked=0.0,
        open_positions_count=0, net_positions_count=0,
        non_margin_positions_value=0.0, calculation_reliability="Ok",
    )


def _cash_row(account_id, amount_account_ccy, booking_id):
    """入金の台帳行。amount_jpy は BookedAmountAccountCurrency (=口座通貨額)。"""
    return {
        "trade_date": date(2026, 8, 31), "settlement_date": date(2026, 8, 31),
        "type": "deposit", "instrument": "CASHINTRTP", "quantity": None,
        "price_per_unit": None, "amount": 1252.06, "currency": "USD",
        "fx_rate": 159.74, "amount_jpy": amount_account_ccy,
        "realized_pnl": None, "broker_ref": booking_id, "order_id": None,
        "account_id": account_id, "source": "test", "updated_at": datetime(2026, 9, 1),
    }


class TestReconcileCash:
    """ライブ settled cash ↔ 台帳キャッシュフロー累計 の第4層 (issue #35)。

    3層照合は buy/sell の数量しか見ないため、現金行が丸ごと欠けても全層一致する。
    2026-08-31 に入金 ¥200,000 の取り込み漏れを「✓ 差分なし」と報告した欠陥を塞ぐ層。
    """

    def test_no_break_when_cash_matches(self, db, tmp_path):
        """台帳の累計キャッシュフローがライブ settled cash と一致 → break なし。"""
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([_cash_row("77800/T126816", 200000.0, "B1")], p)
        breaks = db.reconcile_cash(
            [_balance("77800/T126816", "JPY", 200000.0)], str(p))
        assert breaks == []

    def test_break_when_deposit_not_mirrored(self, db, tmp_path):
        """issue #35 の再現: ライブに ¥255,850 / 台帳は ¥55,850 → 差 ¥200,000 を名指しする。

        これが「✓ 差分なし」と報告されていた断面。
        """
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([_cash_row("77800/T126816", 55850.0, "B1")], p)
        breaks = db.reconcile_cash(
            [_balance("77800/T126816", "JPY", 255850.0)], str(p))
        assert len(breaks) == 1
        b = breaks[0]
        assert b["account_id"] == "77800/T126816"
        assert b["currency"] == "JPY"
        assert b["live_cash"] == 255850.0
        assert b["ledger_cash"] == 55850.0
        assert b["diff"] == 200000.0  # live - ledger > 0 = 台帳に未計上

    def test_buy_and_sell_rows_count_toward_cash(self, db, tmp_path):
        """現金残高は入出金だけでなく約定の記帳額も含む (buy=負 / sell=正)。"""
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([
            _cash_row("77800/T126816", 200000.0, "B1"),
            _ledger_row("SOXL", "buy", 3.0, "OA", "TA"),   # amount_jpy = 1.0
        ], p)
        breaks = db.reconcile_cash(
            [_balance("77800/T126816", "JPY", 200001.0)], str(p))
        assert breaks == []

    def test_zero_zero_accounts_are_skipped(self, db, tmp_path):
        """残高も台帳行も無い空口座 (6件ある) は照合対象にしない。"""
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([_cash_row("77800/T126816", 100.0, "B1")], p)
        breaks = db.reconcile_cash([
            _balance("77800/T126816", "JPY", 100.0),
            _balance("77800/N122798", "USD", 0.0),
        ], str(p))
        assert breaks == []

    def test_ledger_account_missing_from_live_is_a_break(self, db, tmp_path):
        """台帳に現金の動きがあるのにライブ balance に現れない口座 → 見逃さず break。"""
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([_cash_row("77800/UNKNOWN", 50000.0, "B1")], p)
        breaks = db.reconcile_cash(
            [_balance("77800/T126816", "JPY", 0.0)], str(p))
        assert len(breaks) == 1
        assert breaks[0]["account_id"] == "77800/UNKNOWN"
        assert breaks[0]["live_cash"] == 0.0

    def test_sub_yen_noise_is_not_a_break(self, db, tmp_path):
        """JPY は整数円。1円未満の丸め差で break を出さない。"""
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([_cash_row("77800/T126816", 255850.4, "B1")], p)
        breaks = db.reconcile_cash(
            [_balance("77800/T126816", "JPY", 255850.0)], str(p))
        assert breaks == []

    def test_usd_account_uses_cent_tolerance(self, db, tmp_path):
        """USD 口座は 0.01 単位。¥1 相当の緩さを USD に持ち込まない。"""
        p = tmp_path / "tx.parquet"
        write_transactions_parquet([_cash_row("77800/N122798", 100.00, "B1")], p)
        breaks = db.reconcile_cash(
            [_balance("77800/N122798", "USD", 100.50)], str(p))
        assert len(breaks) == 1
        assert breaks[0]["diff"] == 0.5

    def test_missing_parquet_treated_as_empty_ledger(self, db, tmp_path):
        """台帳ファイルが無い時に黙って一致扱いしない。"""
        breaks = db.reconcile_cash(
            [_balance("77800/T126816", "JPY", 255850.0)],
            str(tmp_path / "none.parquet"))
        assert len(breaks) == 1
        assert breaks[0]["ledger_cash"] == 0.0
