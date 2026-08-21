"""保有建玉の含み損益を1行で出す snapshot ツール。

通知欄(モバイル push / terminal-notifier)にそのまま載せられる短文を作ることが目的。
`--line` は1行、`--json` は機械可読。

建玉は Saxo のライブ snapshot から取る(ADR-035: live 情報は ad-hoc に書かず
意味的アクセサ経由)。現値は `src/realtime.py` の延長時間対応クォート(ADR-031)。
為替は yfinance の USDJPY=X。取得できない場合は円換算を出さず $ と % だけを出す
(推測値を通知欄に出さないため)。

含み損益は必ずドル額と % を併記する(CLAUDE.md Rules)。% は
  - entry_pct: エントリー額に対する率(建玉の成績)
  - acct_pct:  口座評価額に対する率(口座インパクト)
の2種類を出す。どちらか一方だけだと規模感を誤る。

使い方:
    python scripts/position_pnl.py --line
    python scripts/position_pnl.py --json
    python scripts/position_pnl.py --line --symbol SOXL
"""
import argparse
import json
import sys
from datetime import timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb  # noqa: E402

from src.db import SenseiDB, now_jst  # noqa: E402
from src.realtime import fetch_realtime_quote  # noqa: E402
from src.saxo_client import SaxoClient  # noqa: E402

JST = timezone(timedelta(hours=9))
DB_PATH = Path(__file__).parent.parent / "data" / "sensei.duckdb"


def fetch_usdjpy() -> float | None:
    """USD/JPY を取得。失敗したら None(円換算を出さない)。"""
    try:
        import yfinance as yf

        hist = yf.Ticker("USDJPY=X").history(period="1d", interval="1m")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def build_snapshot(symbol: str | None = None) -> dict | None:
    """ライブ建玉 + 現値から含み損益 snapshot を作る。建玉が無ければ None。"""
    conn = duckdb.connect(str(DB_PATH))
    try:
        db = SenseiDB(conn)
        client = SaxoClient(db)
        positions = client.get_live_positions()
        balances = client.get_all_account_balances()
    finally:
        conn.close()

    if symbol:
        positions = [p for p in positions if p.symbol == symbol]
    if not positions:
        return None

    pos = positions[0]
    quote = fetch_realtime_quote(pos.symbol)
    fx = fetch_usdjpy()

    qty = pos.amount
    entry = pos.open_price
    price = quote.price
    pnl_usd = (price - entry) * qty
    entry_cost_usd = entry * qty
    entry_pct = (price / entry - 1.0) * 100.0

    # 口座評価額は建玉のある口座のもの(spending_power ではなく total_value)。
    acct_total = None
    for b in balances:
        if b.account_id == pos.account_id:
            acct_total = b.total_value
            break

    pnl_jpy = pnl_usd * fx if fx else None
    acct_pct = None
    if pnl_jpy is not None and acct_total:
        acct_pct = pnl_jpy / acct_total * 100.0

    return {
        "symbol": pos.symbol,
        "quantity": qty,
        "entry_price": entry,
        "price": price,
        "session": quote.session,
        "is_thin": quote.is_thin,
        "regular_close": quote.regular_close,
        "delta_pct_vs_close": quote.delta_pct,
        "bar_time_et": quote.bar_time_et.isoformat(),
        "fetched_at": quote.fetched_at.isoformat(),
        "pnl_usd": pnl_usd,
        "entry_cost_usd": entry_cost_usd,
        "entry_pct": entry_pct,
        "pnl_jpy": pnl_jpy,
        "acct_total_jpy": acct_total,
        "acct_pct": acct_pct,
        "usdjpy": fx,
    }


def format_line(s: dict) -> str:
    """通知欄用の1行。含み損益が真っ先に読めるように先頭に置く。"""
    sign = "+" if s["pnl_usd"] >= 0 else ""
    head = f"{s['symbol']} 含み {sign}{s['pnl_usd']:,.0f}$ ({sign}{s['entry_pct']:.2f}%)"
    if s["pnl_jpy"] is not None:
        head += f" / {sign}{s['pnl_jpy']:,.0f}円"
        if s["acct_pct"] is not None:
            head += f" 口座{sign}{s['acct_pct']:.2f}%"
    body = (
        f" | 現値${s['price']:.2f} 建値${s['entry_price']:.3f} {s['quantity']:g}株"
        f" | {s['session']}"
    )
    if s["is_thin"]:
        body += "(薄商い)"
    body += f" {now_jst().strftime('%H:%M')}JST"
    return head + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None, help="対象シンボル(既定: 最初の建玉)")
    ap.add_argument("--line", action="store_true", help="通知欄用の1行を出す")
    ap.add_argument("--json", action="store_true", help="機械可読JSONを出す")
    args = ap.parse_args()

    snap = build_snapshot(args.symbol)
    if snap is None:
        print("建玉なし")
        return 1

    if args.json:
        print(json.dumps(snap, ensure_ascii=False))
    else:
        print(format_line(snap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
