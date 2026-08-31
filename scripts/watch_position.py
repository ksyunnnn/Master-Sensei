"""保有建玉の含み損益を監視して通知する常駐ツール（issue #27）。

セッションごとに scratchpad で作り直していた監視スクリプトを repo の資産にした
もの。過去5回踏んだバグを仕様として固定してある:

  1. DuckDB 接続を保持しない（毎サイクル開いて閉じる）。保持すると
     `saxo_keepalive.py` を lock で落とす。
  2. 「初回の観測」と「変化の検出」を `None` sentinel で区別する。`0`/`False`
     初期化だと再起動のたびに偽の約定通知が出る。
  3. 起動時に既に跨いでいる水準を遡って鳴らさない（初回は黙って取り込む）。
  4. 通知はヒステリシス付き。基準は「最後に通知した値」で、バケット番号では
     判定しない（境界往復で連発するため）。
  5. 静音区間 09:00-21:30 JST は価格由来の通知を止める（K-070: 04:00-08:00 ET
     の板が枯れた気配で誤報が出る）。ただし静音中も基準値は更新し続ける
     （止めると区間明けに一発目が必ず誤報になる）。

建玉は **DuckDB の執行事実層**（`account_transactions`, ADR-030/035）から FIFO で
導出する。Saxo のライブ snapshot は使わない（token 失効に監視が巻き込まれるのを
避けるため）。ライブ建玉との照合が要る時は `/sync-saxo` を先に回す。

含み損益は Saxo の `unrealized_pnl_base` でなく現値から自前計算する（K-048）。
現値は `src/realtime.py` の延長時間対応クォート（ADR-031）。

使い方:
    # 現況を1回出して終了
    python scripts/watch_position.py --once

    # 監視開始（既定: 60秒ポーリング、翌朝 05:10 JST まで）
    python scripts/watch_position.py

    # 1%刻みでなく 0.5% 動くたびに通知、30分ごとに定期通知
    python scripts/watch_position.py --step 0.5 --heartbeat-min 30
"""
import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb  # noqa: E402

JST = timezone(timedelta(hours=9))
# 執行事実層 (ADR-030/035)。`SenseiDB.ensure_ledger_views` が
# `account_transactions` ビューとして貼るのと同じファイル。
LEDGER_PARQUET = (
    Path(__file__).parent.parent / "data" / "parquet" / "account" / "transactions.parquet"
)

QUIET_START = dtime(9, 0)
QUIET_END = dtime(21, 30)


# ── データ構造 ───────────────────────────────────────────

@dataclass(frozen=True)
class Txn:
    """執行事実層の1約定。`account_transactions` の1行に対応する。"""
    trade_date: date
    kind: str          # 'buy' | 'sell'
    quantity: float
    amount: float      # 買いは負（現金流出）、売りは正。手数料込み。


@dataclass(frozen=True)
class Position:
    """FIFO で導出した現在の建玉。"""
    quantity: float
    cost_usd: float    # 手数料込みの取得原価（正の数）
    avg_price: float   # 取得原価 ÷ 株数


# ── 純粋ロジック（tests/test_watch_position.py で検証） ──────

def fifo_open_position(txns: list[Txn]) -> Optional[Position]:
    """約定履歴から現在の建玉を FIFO で導出する。建玉が無ければ None。

    FIFO は必ず「最後に買った net 株数」を残す（売りは古い lot から消えるため）。
    そこで前から消し込むのではなく、**net 株数を先に確定し、新しい買いから
    さかのぼって net 株数ぶんを取る**。この形にすると、台帳が途中から始まって
    いても正しい建玉になる。

    前から消し込む実装では、対応する買いが台帳の外にある古い売りが「消す先が
    無い」まま捨てられ、その分だけ建玉が過大になる。実際 SOXL の台帳は途中から
    しか無く、素朴な FIFO は 25 株の建玉を 51 株と誤って返した。

    部分的に残る lot は株数比で取得原価を按分する（lot 内の単価は一定）。
    """
    net_qty = sum(
        t.quantity if t.kind == "buy" else -t.quantity
        for t in txns
        if t.kind in ("buy", "sell")
    )
    if net_qty <= 1e-9:
        return None

    buys = [t for t in sorted(txns, key=lambda x: x.trade_date) if t.kind == "buy"]
    remaining = net_qty
    cost = 0.0
    for t in reversed(buys):
        if remaining <= 1e-9:
            break
        take = min(t.quantity, remaining)
        cost += abs(t.amount) * (take / t.quantity)
        remaining -= take

    if remaining > 1e-9:
        raise RuntimeError(
            f"台帳の買いが net 建玉 {net_qty:g} 株に足りない（{remaining:g} 株ぶん不明）。"
            "/sync-saxo で mirror を確認する"
        )

    return Position(quantity=net_qty, cost_usd=cost, avg_price=cost / net_qty)


def pnl_snapshot(pos: Position, price: float) -> dict:
    """現値から含み損益を計算する。率は取得原価比と約定単価比の2本を出す。

    手数料の分だけ取得原価比のほうが悪く出る。片方だけ出すと、報告のたびに
    損益率が変わって見えるので両方持つ。
    """
    market_value = price * pos.quantity
    pnl_usd = market_value - pos.cost_usd
    return {
        "market_value_usd": market_value,
        "pnl_usd": pnl_usd,
        "pnl_pct_cost": pnl_usd / pos.cost_usd * 100.0,
        "pnl_pct_entry": (price / pos.avg_price - 1.0) * 100.0,
    }


def is_quiet_jst(now: datetime) -> bool:
    """価格由来の通知を止める静音区間か（K-070）。区間は [09:00, 21:30) JST。"""
    t = now.astimezone(JST).time()
    return QUIET_START <= t < QUIET_END


def check_level_alerts(
    *,
    prev_price: Optional[float],
    price: float,
    above: list,
    below: list,
    fired: set,
) -> list:
    """指定した価格水準を跨いだかを判定する。跨いだ水準を [(向き, 水準), ...] で返す。

    `fired` は呼び出し側が持ち回る「もう鳴らした水準」の集合で、この関数が破壊的に
    更新する。同じ水準は監視1回につき一度しか鳴らない（issue #27 バグ #4 と同じ規律。
    境界を往復するたびに鳴ると通知が意味を失うため、再武装はしない）。

    `prev_price is None` は監視開始時の初回観測。**この時点で既に跨いでいる水準は
    黙って fired に入れ、鳴らさない**（issue #27 バグ #3。起動しただけで過去の水準が
    一斉に鳴るのを防ぐ）。

    同値は上抜け扱い（`price >= level`）。指値の約定判定と揃えてある。
    """
    if prev_price is None:
        for lv in above:
            if price >= lv:
                fired.add(("above", lv))
        for lv in below:
            if price <= lv:
                fired.add(("below", lv))
        return []

    hits = []
    for lv in sorted(above):
        key = ("above", lv)
        if key not in fired and prev_price < lv <= price:
            fired.add(key)
            hits.append(key)
    for lv in sorted(below, reverse=True):
        key = ("below", lv)
        if key not in fired and prev_price > lv >= price:
            fired.add(key)
            hits.append(key)
    return hits


def should_notify_move(
    last_notified_pct: Optional[float], current_pct: float, step: float
) -> bool:
    """含み損益率が「最後に通知した値」から step 以上動いたか。

    `last_notified_pct is None` は初回観測。黙って取り込むだけで通知しない
    （issue #27 バグ #2/#3）。
    """
    if last_notified_pct is None:
        return False
    return abs(current_pct - last_notified_pct) >= step


def format_notification(
    *,
    symbol: str,
    snap: dict,
    price: float,
    session: str,
    is_thin: bool,
    now: datetime,
    usdjpy: Optional[float],
) -> str:
    """通知欄の1行。含み損益を先頭に置き、ドル額と％を必ず併記する。"""
    pnl = snap["pnl_usd"]
    sign = "+" if pnl >= 0 else ""
    head = f"{sign}{pnl:,.0f}$ ({sign}{snap['pnl_pct_cost']:.2f}%)"
    if usdjpy:
        head += f" / {sign}{pnl * usdjpy:,.0f}円"
    body = f" | {symbol} ${price:.2f} [{session}]"
    if is_thin:
        body += "薄商い"
    body += f" {now.astimezone(JST):%H:%M}JST"
    return head + body


# ── 副作用（DB・価格・通知） ──────────────────────────────

def load_position(symbol: str) -> Optional[Position]:
    """執行事実層から建玉を引く。

    `sensei.duckdb` は **開かない**。ADR-030 の正本は Parquet 側であり、監視の
    常駐プロセスが DB ロックを握ると `saxo_keepalive.py` や `update_data.py` を
    落とす（issue #27 バグ #1）。in-memory 接続で parquet を直読みし、毎回閉じる。
    """
    if not LEDGER_PARQUET.exists():
        raise RuntimeError(
            f"執行事実層が無い: {LEDGER_PARQUET}。/sync-saxo で mirror してから監視する"
        )

    conn = duckdb.connect(":memory:")
    try:
        rows = conn.execute(
            "SELECT trade_date, type, quantity, amount FROM read_parquet(?) "
            "WHERE instrument = ? AND type IN ('buy','sell') ORDER BY trade_date",
            [str(LEDGER_PARQUET), symbol],
        ).fetchall()
    finally:
        conn.close()

    txns = [Txn(trade_date=r[0], kind=r[1], quantity=float(r[2]), amount=float(r[3]))
            for r in rows]
    return fifo_open_position(txns)


def fetch_usdjpy() -> Optional[float]:
    """USD/JPY。取れなければ None（推測した円換算を通知欄に出さない）。"""
    try:
        import yfinance as yf

        hist = yf.Ticker("USDJPY=X").history(period="1d", interval="1m")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def notify(title: str, subtitle: str, msg: str) -> None:
    try:
        subprocess.run(
            ["terminal-notifier", "-title", title, "-subtitle", subtitle,
             "-message", msg, "-sound", "default"],
            check=False, capture_output=True,
        )
    except FileNotFoundError:
        pass


def _resolve_end(until: str) -> datetime:
    hh, mm = (int(x) for x in until.split(":"))
    now = datetime.now(JST)
    end = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if end <= now:
        end += timedelta(days=1)
    return end


def run(*, symbol: str, poll_sec: int, step: float, heartbeat_min: int,
        end_at: datetime, once: bool,
        alert_above: Optional[list] = None,
        alert_below: Optional[list] = None) -> int:
    from src.realtime import fetch_realtime_quote

    last_notified_pct: Optional[float] = None   # None = 未観測（issue #27 バグ #2）
    last_qty: Optional[float] = None            # None = 未観測
    last_heartbeat: Optional[datetime] = None
    fx: Optional[float] = None
    fx_at: Optional[datetime] = None
    prev_price: Optional[float] = None   # None = 未観測（水準アラートを遡らせない）
    fired_levels: set = set()
    above = list(alert_above or [])
    below = list(alert_below or [])

    while True:
        now = datetime.now(JST)
        if not once and now >= end_at:
            print(f"[END {now:%H:%M:%S}] scheduled stop", flush=True)
            notify("Master Sensei", "建玉監視", f"{symbol} 監視を終了しました ({end_at:%H:%M} JST)")
            return 0

        pos = load_position(symbol)
        if pos is None:
            print(f"[{now:%H:%M:%S}] {symbol} 建玉なし", flush=True)
            if last_qty:
                notify("Master Sensei", "建玉監視", f"{symbol} の建玉が DB から消えました（決済反映）")
            last_qty = 0.0
            if once:
                return 1
            time.sleep(poll_sec)
            continue

        try:
            quote = fetch_realtime_quote(symbol)
        except Exception as exc:
            print(f"[{now:%H:%M:%S}] 現値取得エラー: {exc}", flush=True)
            if once:
                return 1
            time.sleep(poll_sec)
            continue

        snap = pnl_snapshot(pos, quote.price)
        pct = snap["pnl_pct_cost"]

        if fx is None or fx_at is None or (now - fx_at) > timedelta(minutes=10):
            fx = fetch_usdjpy()
            fx_at = now

        line = format_notification(
            symbol=symbol, snap=snap, price=quote.price, session=quote.session,
            is_thin=quote.is_thin, now=now, usdjpy=fx,
        )
        # 基準終値が stale だと delta_pct は None (ADR-031)。その時は「終値比」を
        # 出さず、基準がいつのもので何営業日古いかを名指しする。
        if quote.delta_pct is None:
            cmp_part = (
                f"終値比なし: 基準{quote.regular_close_date:%m-%d}が"
                f"{quote.baseline_stale_days}営業日古い"
            )
        else:
            cmp_part = f"{quote.regular_close_date:%m-%d}終値比{quote.delta_pct:+.2f}%"
        detail = (
            f"{line} | {pos.quantity:g}株 建値${pos.avg_price:.3f} "
            f"原価${pos.cost_usd:,.2f} 評価${snap['market_value_usd']:,.2f} "
            f"({cmp_part})"
        )
        print(f"[{now:%H:%M:%S}] {detail}", flush=True)

        quiet = is_quiet_jst(now)

        # 水準アラートは静音区間でも鳴らす。指定した価格で行動するために
        # 設定するものなので、止めると設定した意味が無くなる。薄商いかどうかは
        # format_notification が文面に出す（K-070 の誤報は文面で警告する方針）。
        for direction, level in check_level_alerts(
            prev_price=prev_price, price=quote.price,
            above=above, below=below, fired=fired_levels,
        ):
            mark = "到達" if direction == "above" else "割れ"
            notify("Master Sensei", f"水準{mark} ${level:g}", line)
        prev_price = quote.price

        # 約定・建玉変化は静音区間でも常に通知する（issue #27 の仕様）
        if last_qty is not None and abs(pos.quantity - last_qty) > 1e-9:
            notify("Master Sensei", "建玉変化",
                   f"{symbol} {last_qty:g}株 → {pos.quantity:g}株 | {line}")
            last_notified_pct = pct
        last_qty = pos.quantity

        if once:
            notify("Master Sensei", "建玉スナップショット", line)
            return 0

        due_heartbeat = (
            heartbeat_min > 0
            and (last_heartbeat is None or (now - last_heartbeat) >= timedelta(minutes=heartbeat_min))
        )

        if last_notified_pct is None:
            # 監視開始の1発目。静音区間でも出す（起動できたことの確認であって、
            # 値動きに反応した通知ではないため）。同時に比較の基準を置く。
            notify("Master Sensei", "建玉監視 開始", line)
            last_notified_pct = pct
            last_heartbeat = now
        elif quiet:
            # 静音中は通知を止めるが、基準値は進め続ける
            # （止めると区間明けの一発目が必ず誤報になる）
            last_notified_pct = pct
        else:
            if should_notify_move(last_notified_pct, pct, step):
                arrow = "↑" if pct > last_notified_pct else "↓"
                notify("Master Sensei", f"含み {arrow}{abs(pct - last_notified_pct):.1f}pt", line)
                last_notified_pct = pct
                last_heartbeat = now
            elif due_heartbeat:
                notify("Master Sensei", "建玉監視", line)
                last_heartbeat = now

        time.sleep(poll_sec)


def main() -> int:
    ap = argparse.ArgumentParser(description="保有建玉の含み損益監視（建玉は DuckDB 執行事実層から）")
    ap.add_argument("--symbol", default="SOXL", help="監視対象シンボル")
    ap.add_argument("--poll-sec", type=int, default=60, help="ポーリング間隔（秒）")
    ap.add_argument("--step", type=float, default=1.0,
                    help="含み損益率がこの pt 動いたら通知（最後に通知した値が基準）")
    ap.add_argument("--heartbeat-min", type=int, default=30,
                    help="動きが無くても通知する間隔（分）。0 で無効")
    ap.add_argument("--until", default="05:10", help="終了時刻 HH:MM JST（過ぎていれば翌日）")
    ap.add_argument("--once", action="store_true", help="現況を1回出して終了")
    ap.add_argument("--alert-above", type=float, action="append", metavar="PRICE",
                    help="この価格に到達したら通知（複数指定可）。監視1回につき一度だけ鳴る")
    ap.add_argument("--alert-below", type=float, action="append", metavar="PRICE",
                    help="この価格を割れたら通知（複数指定可）。監視1回につき一度だけ鳴る")
    args = ap.parse_args()

    return run(
        symbol=args.symbol.upper(),
        poll_sec=args.poll_sec,
        step=args.step,
        heartbeat_min=args.heartbeat_min,
        end_at=_resolve_end(args.until),
        once=args.once,
        alert_above=args.alert_above,
        alert_below=args.alert_below,
    )


if __name__ == "__main__":
    raise SystemExit(main())
