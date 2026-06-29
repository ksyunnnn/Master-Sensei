"""Saxo 照合の機械的エントリポイント (ADR-030)。

`/sync-saxo` の重い手順を1本に畳む。差分ゼロなら数秒・1ステップで終わる:

  1. **無言 token 確保** — `get_access_token()` を呼ぶだけ。refresh token が生きていれば
     自動更新で無言通過。失効時のみ `AUTH_REQUIRED` を出して exit 2 (呼び出し側が
     `scripts/saxo_oauth_init.py` をブラウザ起動 → 再実行)。手動の expires_at 点検は廃止。
  2. **テール窓 mirror** — 既存 parquet の最新 trade_date から overlap 日だけ遡って
     reports/trades + bookings を再取得し、broker_ref で upsert マージ (全年 mirror を回さない)。
     `--full` で全年に倒せる (窓より前の遡及訂正を拾う逃げ道)。
  3. **3層照合** — ライブ Saxo (建玉+注文) ↔ 執行事実層(parquet) ↔ 判断層 trades を突合:
     a. **live建玉 ↔ 台帳 net** … mirror 漏れ検出。乖離時は窓を段階拡大して**自動再mirror**
        (tail→30d→90d→全年)、各段階で再照合し解消した時点で止める (重い全年は最後の手段)。
     b. **台帳 net ↔ trades 申告** … クローズ済未反映/未記録エントリーの検出 (従来層)。
     c. **liveライブ注文 ↔ trades placed** … placed の改定/不発/未記録の検出 (台帳に出ない層)。
     どの層も差分が無ければ `✓` で終了。差分は層ごとに分類して人間に報告する。

実行: python scripts/sync_saxo.py [--full] [--overlap-days N]
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import timedelta
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.account_ledger import (
    DEFAULT_FROM_DATE,
    DEFAULT_OVERLAP_DAYS,
    cash_bookings_to_rows,
    latest_trade_date,
    merge_transactions_parquet,
    trade_reports_to_rows,
    window_from_date,
    write_transactions_parquet,
)
from src.db import SenseiDB, now_jst, today_jst
from src.saxo_client import SaxoAuthError, SaxoClient

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "sensei.duckdb"
PARQUET_PATH = (
    Path(__file__).parent.parent / "data" / "parquet" / "account" / "transactions.parquet"
)

# live≠台帳 検出時の再mirror 窓 (日数)。tail で解消しなければ段階的に広げ、
# 最後に全年へ escalate する。重い全年取得を「最後の手段」に留めるための階段。
ESCALATION_WINDOWS = [30, 90]

EXIT_OK = 0
EXIT_BREAKS = 1       # 差分(break)あり: 人間の確認が要る
EXIT_AUTH = 2         # token 失効: 呼び出し側が oauth_init を起動して再実行


def _net_by_symbol(positions) -> dict[str, float]:
    """LivePosition のリストを {symbol: net_amount} に集計する。"""
    net: dict[str, float] = {}
    for p in positions:
        net[p.symbol] = net.get(p.symbol, 0.0) + p.amount
    return {s: q for s, q in net.items() if abs(q) > 1e-9}


def _fetch_window_rows(client: SaxoClient, from_date: str, to_date: str) -> list[dict]:
    """全 active client_key について [from_date, to_date] の約定+現金行を集める。"""
    updated_at = now_jst()
    rows: list[dict] = []
    for ck in sorted({a["ClientKey"] for a in client.get_accounts()}):
        reports = client.get_trade_reports(client_key=ck, from_date=from_date, to_date=to_date)
        rows.extend(trade_reports_to_rows(
            reports, source="saxo_reports_trades", updated_at=updated_at))
        bookings = client.get_bookings(client_key=ck, from_date=from_date, to_date=to_date)
        rows.extend(cash_bookings_to_rows(
            bookings, source="saxo_reports_bookings", updated_at=updated_at))
        logger.info("ClientKey %s: %d fills, %d cash (since %s)",
                    ck, len(reports), len(bookings), from_date)
    return rows


def _mirror_full(client: SaxoClient, to_date: str) -> None:
    """全年 mirror (全置換)。窓より前の遡及訂正を拾う最後の手段。"""
    rows = _fetch_window_rows(client, DEFAULT_FROM_DATE, to_date)
    n = write_transactions_parquet(rows, PARQUET_PATH)
    print(f"[mirror] full: {DEFAULT_FROM_DATE}→{to_date}, {n} 行 全置換")


def _mirror_tail(client: SaxoClient, to_date: str, overlap_days: int) -> None:
    """テール窓 mirror (anchor=最新trade_date − overlap)。初回は全年。"""
    anchor = latest_trade_date(PARQUET_PATH)
    from_date = window_from_date(
        anchor, overlap_days=overlap_days, default_from=DEFAULT_FROM_DATE)
    rows = _fetch_window_rows(client, from_date, to_date)
    n = merge_transactions_parquet(rows, PARQUET_PATH)
    mode = "full(初回)" if anchor is None else f"tail(overlap{overlap_days}d)"
    print(f"[mirror] {mode}: {from_date}→{to_date}, 取得{len(rows)}行 → 台帳{n}行")


def _mirror_window_days(client: SaxoClient, to_date: str, days: int) -> None:
    """今日から `days` 日遡った固定窓を upsert マージ (escalation 用)。"""
    from_date = str(today_jst() - timedelta(days=days))
    rows = _fetch_window_rows(client, from_date, to_date)
    n = merge_transactions_parquet(rows, PARQUET_PATH)
    print(f"[re-mirror] 窓 {days}d ({from_date}→{to_date}): 取得{len(rows)}行 → 台帳{n}行")


def _reconcile_live_with_escalation(
    db: SenseiDB, client: SaxoClient, live_net: dict, to_date: str, *, full: bool
) -> list[dict]:
    """live建玉 ↔ 台帳 を突合。乖離時は窓を段階拡大して自動再mirror→再照合する。

    解消した時点で止め、全年まで広げても残った break を返す。`full=True` (既に全年
    mirror 済み) のときは escalation しない (これ以上広げる先が無いため)。
    """
    breaks = db.reconcile_live_positions(live_net, str(PARQUET_PATH))
    if not breaks or full:
        return breaks
    print(f"⚠ live≠台帳 {len(breaks)}件 検出 → mirror 漏れの可能性。窓を拡大して自動再mirror:")
    for days in ESCALATION_WINDOWS:
        _mirror_window_days(client, to_date, days)
        breaks = db.reconcile_live_positions(live_net, str(PARQUET_PATH))
        if not breaks:
            print(f"  ✓ 解消 (窓 {days}d で台帳が追いついた)")
            return breaks
    print("  なお残存 → 全年 mirror に escalate")
    _mirror_full(client, to_date)
    return db.reconcile_live_positions(live_net, str(PARQUET_PATH))


def run_sync(*, full: bool, overlap_days: int) -> int:
    conn = duckdb.connect(str(DB_PATH))
    try:
        db = SenseiDB(conn)
        client = SaxoClient(db)

        # 1. 無言 token 確保 (refresh 生存時は自動更新で無言通過)。
        try:
            client.get_access_token()
        except SaxoAuthError as e:
            print(f"AUTH_REQUIRED: {e}", file=sys.stderr)
            print("→ scripts/saxo_oauth_init.py をブラウザ起動 (ログインのみ) 後、再実行",
                  file=sys.stderr)
            return EXIT_AUTH

        # 2. mirror: 既定はテール窓、--full で全年。
        to_date = str(today_jst())
        if full:
            _mirror_full(client, to_date)
        else:
            _mirror_tail(client, to_date, overlap_days)

        # 3. ライブ snapshot 取得 (安い: 建玉+注文の各1コール)。
        live_net = _net_by_symbol(client.get_live_positions())
        live_order_ids = {o.order_id for o in client.get_open_orders()}

        # 3a. live建玉 ↔ 台帳 (mirror 漏れ。乖離時は自動再mirror で埋める)。
        live_breaks = _reconcile_live_with_escalation(
            db, client, live_net, to_date, full=full)
        # 3b. 台帳 ↔ trades 申告 (従来層)。
        ledger_breaks = db.reconcile_positions(str(PARQUET_PATH))
        # 3c. liveライブ注文 ↔ trades placed (台帳に出ない層)。
        order_breaks = db.reconcile_open_orders(live_order_ids)

        if not (live_breaks or ledger_breaks or order_breaks):
            print("✓ 差分なし (ライブ建玉↔台帳↔trades 一致 / 注文も一致)")
            return EXIT_OK

        total = len(live_breaks) + len(ledger_breaks) + len(order_breaks)
        print(f"⚠ break {total}件 (ADR-030 で分類・人間が確認):")
        for b in live_breaks:
            print(f"  - [live↔台帳] {_classify_live_break(b)}")
        for b in ledger_breaks:
            print(f"  - [台帳↔trades] {_classify_break(b)}")
        for b in order_breaks:
            print(f"  - [注文] {_classify_order_break(b)}")
        print("注: 修正は SenseiDB メソッド経由・物理削除しない (ADR-018/030)")
        return EXIT_BREAKS
    finally:
        conn.close()


def _classify_break(b: dict) -> str:
    """台帳↔trades の break を ADR-030 の遷移カテゴリに分類して説明文にする。"""
    sym, tq, lq = b["instrument"], b["trades_open_qty"], b["ledger_net_qty"]
    base = f"{sym}: trades申告={tq:g} / 台帳実態={lq:g}"
    if tq != 0 and lq == 0:
        return f"{base} → クローズ済未反映 (close_trade で exit を台帳sell fillから)"
    if tq == 0 and lq > 0:
        return f"{base} → 未記録エントリー (add_trade status=filled, broker_ref=OrderId)"
    if lq == 0 and tq == 0:
        return f"{base} → 両建てゼロ (要個別確認)"
    return f"{base} → 数量不一致 (注文改定/部分約定の未反映? 個別確認)"


def _classify_live_break(b: dict) -> str:
    """live建玉↔台帳 の break を分類する。再mirror でも残った=真の乖離。"""
    sym, live, ledger = b["instrument"], b["live_net_qty"], b["ledger_net_qty"]
    base = f"{sym}: ライブ建玉={live:g} / 台帳net={ledger:g}"
    if abs(live) > abs(ledger):
        return (f"{base} → 台帳の取りこぼし (全年mirror でも未補填: "
                "reports/trades の欠落 or instrument 解決失敗を要調査)")
    return (f"{base} → 台帳に余分 (クローズ/反対売買の未mirror or "
            "ライブ側決済済みを要確認)")


def _classify_order_break(b: dict) -> str:
    """liveライブ注文↔trades placed の break を分類する。"""
    side = b["side"]
    if side == "live_only":
        return (f"OrderId={b['order_id']} → ライブに注文あるが trades 未記録 "
                "(add_trade status='placed', broker_ref=OrderId)")
    if side == "trades_only":
        return (f"OrderId={b['order_id']} ({b['instrument']} {b['quantity']:g}) "
                "→ trades は placed だがライブに無し (約定→filled / 失効→expired / 取消→cancelled)")
    return (f"placed だが broker_ref 未設定 ({b['instrument']} {b['quantity']:g}) "
            "→ OrderId を set_trade_broker_ref で補完")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Saxo 照合 (token→tail-window mirror→reconcile)")
    parser.add_argument("--full", action="store_true",
                        help="全年 mirror (窓より前の遡及訂正を拾う逃げ道)")
    parser.add_argument("--overlap-days", type=int, default=DEFAULT_OVERLAP_DAYS,
                        help=f"テール窓の overlap 日数 (既定 {DEFAULT_OVERLAP_DAYS})")
    args = parser.parse_args()
    sys.exit(run_sync(full=args.full, overlap_days=args.overlap_days))


if __name__ == "__main__":
    main()
