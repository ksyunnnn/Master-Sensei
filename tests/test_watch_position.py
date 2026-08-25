"""scripts/watch_position.py の純粋ロジックのテスト。

監視ループ本体（時刻・ネットワーク・通知）は副作用なので、判定は全部
純粋関数に切り出してここで検証する。issue #27 が挙げた過去5バグのうち
「初回観測と変化検出の混同」「静音区間で基準値まで止める」「境界往復での
連発」の3つは、ここの assert が再発を止める。
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.watch_position import (  # noqa: E402
    Position,
    Txn,
    fifo_open_position,
    format_notification,
    is_quiet_jst,
    pnl_snapshot,
    should_notify_move,
)

JST = timezone(timedelta(hours=9))


# ── FIFO 建玉導出 ────────────────────────────────────────

def _txn(d: date, kind: str, qty: float, amount: float) -> Txn:
    return Txn(trade_date=d, kind=kind, quantity=qty, amount=amount)


def test_fifo_単純な買いのみ():
    txns = [_txn(date(2026, 8, 20), "buy", 25, -3004.84)]
    pos = fifo_open_position(txns)
    assert pos is not None
    assert pos.quantity == 25
    assert pos.cost_usd == pytest.approx(3004.84)
    assert pos.avg_price == pytest.approx(3004.84 / 25)


def test_fifo_全部売り切ったら建玉なし():
    txns = [
        _txn(date(2026, 8, 18), "buy", 12, -1615.30),
        _txn(date(2026, 8, 19), "sell", 12, 1437.84),
    ]
    assert fifo_open_position(txns) is None


def test_fifo_古いlotから先に消える():
    """8/18 の 24 株を 8/19 に手仕舞い、8/20 に 25 株を買い直した実際の履歴。

    残るのは 8/20 の lot だけで、取得原価は 8/18 の高い建値を引きずらない。
    """
    txns = [
        _txn(date(2026, 8, 18), "buy", 12, -1615.30),
        _txn(date(2026, 8, 18), "buy", 12, -1615.30),
        _txn(date(2026, 8, 19), "sell", 12, 1437.84),
        _txn(date(2026, 8, 19), "sell", 12, 1437.84),
        _txn(date(2026, 8, 20), "buy", 25, -3004.84),
    ]
    pos = fifo_open_position(txns)
    assert pos is not None
    assert pos.quantity == 25
    assert pos.cost_usd == pytest.approx(3004.84)
    assert pos.avg_price == pytest.approx(120.1936)


def test_fifo_部分決済は残りlotに按分される():
    txns = [
        _txn(date(2026, 8, 20), "buy", 10, -1000.0),
        _txn(date(2026, 8, 21), "sell", 4, 440.0),
    ]
    pos = fifo_open_position(txns)
    assert pos is not None
    assert pos.quantity == 6
    assert pos.cost_usd == pytest.approx(600.0)
    assert pos.avg_price == pytest.approx(100.0)


def test_fifo_複数lotが残る場合は加重平均():
    txns = [
        _txn(date(2026, 8, 20), "buy", 10, -1000.0),
        _txn(date(2026, 8, 21), "buy", 10, -1200.0),
    ]
    pos = fifo_open_position(txns)
    assert pos is not None
    assert pos.quantity == 20
    assert pos.cost_usd == pytest.approx(2200.0)
    assert pos.avg_price == pytest.approx(110.0)


def test_fifo_取引履歴が空ならNone():
    assert fifo_open_position([]) is None


# ── 含み損益 ─────────────────────────────────────────────

def test_pnl_取得原価ベースと建値ベースを両方出す():
    """手数料込みの取得原価と、約定単価の2つの基準がずれることを保つ。

    Saxo の手数料 $7.87 の分だけ取得原価比のほうが悪く出る。どちらか一方
    しか出さないと、損益率が報告のたびに変わって見える。
    """
    pos = Position(quantity=25, cost_usd=3004.84, avg_price=119.879)
    snap = pnl_snapshot(pos, price=111.16)
    assert snap["market_value_usd"] == pytest.approx(2779.0)
    assert snap["pnl_usd"] == pytest.approx(-225.84)
    assert snap["pnl_pct_cost"] == pytest.approx(-7.5158, abs=1e-3)
    assert snap["pnl_pct_entry"] == pytest.approx(-7.2739, abs=1e-3)


def test_pnl_含み益側も符号が正しい():
    pos = Position(quantity=25, cost_usd=3004.84, avg_price=119.879)
    snap = pnl_snapshot(pos, price=130.0)
    assert snap["pnl_usd"] > 0
    assert snap["pnl_pct_cost"] == pytest.approx(8.1588, abs=1e-3)


# ── 静音区間（K-070） ────────────────────────────────────

@pytest.mark.parametrize(
    "hhmm,expected",
    [
        ((9, 0), True),      # 区間の開始点は静音に含む
        ((14, 30), True),    # 日本の日中＝米国は板が無い
        ((21, 29), True),    # 区間終了の直前
        ((21, 30), False),   # 区間終了点は通知を再開する
        ((22, 30), False),   # 米レギュラー寄り
        ((3, 0), False),     # 米レギュラー後半
        ((8, 59), False),    # 区間開始の直前
    ],
)
def test_静音区間の境界(hhmm, expected):
    now = datetime(2026, 8, 25, hhmm[0], hhmm[1], tzinfo=JST)
    assert is_quiet_jst(now) is expected


# ── 通知判定（初回観測・ヒステリシス） ──────────────────────

def test_初回観測は通知しない():
    """issue #27 バグ #2/#3 と同じ型。None sentinel で「未観測」を表す。

    0.0 で初期化すると、再起動のたびに「0% から現在値まで動いた」と誤検知する。
    """
    assert should_notify_move(last_notified_pct=None, current_pct=-7.5, step=1.0) is False


def test_閾値未満の動きでは通知しない():
    assert should_notify_move(last_notified_pct=-7.5, current_pct=-8.2, step=1.0) is False


def test_閾値を超えたら通知する():
    assert should_notify_move(last_notified_pct=-7.5, current_pct=-8.6, step=1.0) is True
    assert should_notify_move(last_notified_pct=-7.5, current_pct=-6.4, step=1.0) is True


def test_境界の往復で連発しない():
    """基準は「最後に通知した値」なので、境界をまたいで戻っても再発火しない。

    バケット番号で判定すると -8.49 ⇄ -8.51 の往復で毎回鳴る。
    """
    last = -7.5
    assert should_notify_move(last_notified_pct=last, current_pct=-8.51, step=1.0) is True
    # 通知したので基準が -8.51 に移る。そこから境界へ戻っても差は 1.0 未満。
    last = -8.51
    assert should_notify_move(last_notified_pct=last, current_pct=-8.49, step=1.0) is False
    assert should_notify_move(last_notified_pct=last, current_pct=-7.6, step=1.0) is False


# ── 通知文面 ─────────────────────────────────────────────

def test_通知文面にドル額と率が必ず入る():
    """CLAUDE.md Rules: 含み損益はドル額と％を必ず両方出す。"""
    pos = Position(quantity=25, cost_usd=3004.84, avg_price=119.879)
    snap = pnl_snapshot(pos, price=111.16)
    line = format_notification(
        symbol="SOXL", snap=snap, price=111.16, session="regular",
        is_thin=False, now=datetime(2026, 8, 25, 23, 5, tzinfo=JST), usdjpy=None,
    )
    assert "-226" in line or "-225" in line
    assert "%" in line
    assert "SOXL" in line
    assert "23:05" in line


def test_薄商いは文面に出す():
    pos = Position(quantity=25, cost_usd=3004.84, avg_price=119.879)
    snap = pnl_snapshot(pos, price=111.16)
    line = format_notification(
        symbol="SOXL", snap=snap, price=111.16, session="pre",
        is_thin=True, now=datetime(2026, 8, 25, 21, 40, tzinfo=JST), usdjpy=None,
    )
    assert "薄商い" in line


def test_為替が取れなければ円を出さない():
    """推測した円換算を通知欄に出さない（position_pnl.py と同じ規律）。"""
    pos = Position(quantity=25, cost_usd=3004.84, avg_price=119.879)
    snap = pnl_snapshot(pos, price=111.16)
    line = format_notification(
        symbol="SOXL", snap=snap, price=111.16, session="regular",
        is_thin=False, now=datetime(2026, 8, 25, 23, 5, tzinfo=JST), usdjpy=None,
    )
    assert "円" not in line

    line_fx = format_notification(
        symbol="SOXL", snap=snap, price=111.16, session="regular",
        is_thin=False, now=datetime(2026, 8, 25, 23, 5, tzinfo=JST), usdjpy=159.0,
    )
    assert "円" in line_fx


def test_fifo_台帳が途中から始まっていても建玉が過大にならない():
    # 実際の SOXL 台帳と同じ形。冒頭の買いが台帳の外にあり、最初の売りは
    # 対応する買いを持たない。素朴な前方向 FIFO はこの売りを捨てて
    # 建玉を過大に返した(25 株 -> 51 株)。
    txns = [
        _txn(date(2026, 6, 29), "sell", 10, 1974.65),
        _txn(date(2026, 7, 6), "buy", 10, -1969.56),
        _txn(date(2026, 7, 23), "sell", 13, 2084.29),
        _txn(date(2026, 8, 20), "buy", 25, -3004.84),
    ]
    pos = fifo_open_position(txns)
    assert pos is not None
    assert pos.quantity == 12
    # 直近の 8/20 lot から 12 株ぶんだけを取る
    assert pos.cost_usd == pytest.approx(3004.84 * 12 / 25)


def test_fifo_買いが足りなければ黙って返さず落ちる():
    txns = [
        _txn(date(2026, 8, 20), "buy", 5, -500.0),
        _txn(date(2026, 8, 21), "sell", 1, 110.0),
    ]
    # net 4 株に対し買いは 5 株あるので通る
    assert fifo_open_position(txns).quantity == 4
