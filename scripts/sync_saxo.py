"""Saxo 照合の機械的エントリポイント (ADR-030)。

`/sync-saxo` の重い手順を1本に畳む。差分ゼロなら数秒・1ステップで終わる:

  1. **無言 token 確保** — `get_access_token()` を呼ぶだけ。refresh token が生きていれば
     自動更新で無言通過。失効時のみ `AUTH_REQUIRED` を出して exit 2 (呼び出し側が
     `scripts/saxo_oauth_init.py` をブラウザ起動 → 再実行)。手動の expires_at 点検は廃止。
  2. **テール窓 mirror** — 既存 parquet の最新 trade_date から overlap 日だけ遡って
     reports/trades + bookings を再取得し、broker_ref で upsert マージ (全年 mirror を回さない)。
     `--full` で全年に倒せる (窓より前の遡及訂正を拾う逃げ道)。
  3. **reconcile** — 判断層 trades vs 執行事実層(parquet) の純ポジションを突合し break を出す。

実行: python scripts/sync_saxo.py [--full] [--overlap-days N]

注: ライブ未約定注文 (placed の改定/不発) の照合は意味的アクセサ未整備のため本スクリプト
対象外。必要時は SKILL.md の手順で別途確認する (ADR-026: raw dict access 禁止)。
"""
from __future__ import annotations

import argparse
import logging
import sys
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

EXIT_OK = 0
EXIT_BREAKS = 1       # 差分(break)あり: 人間の確認が要る
EXIT_AUTH = 2         # token 失効: 呼び出し側が oauth_init を起動して再実行


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

        # 2. mirror: 既定はテール窓 (anchor=最新trade_date − overlap)、--full で全年。
        to_date = str(today_jst())
        if full:
            from_date = DEFAULT_FROM_DATE
            rows = _fetch_window_rows(client, from_date, to_date)
            n = write_transactions_parquet(rows, PARQUET_PATH)
            print(f"[mirror] full: {from_date}→{to_date}, {n} 行 全置換")
        else:
            anchor = latest_trade_date(PARQUET_PATH)
            from_date = window_from_date(
                anchor, overlap_days=overlap_days, default_from=DEFAULT_FROM_DATE)
            rows = _fetch_window_rows(client, from_date, to_date)
            n = merge_transactions_parquet(rows, PARQUET_PATH)
            mode = "full(初回)" if anchor is None else f"tail(overlap{overlap_days}d)"
            print(f"[mirror] {mode}: {from_date}→{to_date}, 取得{len(rows)}行 → 台帳{n}行")

        # 3. reconcile (台帳ベース、raw dict 不使用)。
        breaks = db.reconcile_positions(str(PARQUET_PATH))
        if not breaks:
            print("✓ 差分なし (trades と台帳が一致)")
            print("注: ライブ未約定注文の照合は別途 (SKILL.md, ADR-026)")
            return EXIT_OK

        print(f"⚠ break {len(breaks)}件 (ADR-030 で分類・人間が確認):")
        for b in breaks:
            print(f"  - {_classify_break(b)}")
        print("注: 修正は SenseiDB メソッド経由・物理削除しない (ADR-018/030)")
        return EXIT_BREAKS
    finally:
        conn.close()


def _classify_break(b: dict) -> str:
    """reconcile の break を ADR-030 の遷移カテゴリに分類して説明文にする。"""
    sym, tq, lq = b["instrument"], b["trades_open_qty"], b["ledger_net_qty"]
    base = f"{sym}: trades申告={tq:g} / 台帳実態={lq:g}"
    if tq != 0 and lq == 0:
        return f"{base} → クローズ済未反映 (close_trade で exit を台帳sell fillから)"
    if tq == 0 and lq > 0:
        return f"{base} → 未記録エントリー (add_trade status=filled, broker_ref=OrderId)"
    if lq == 0 and tq == 0:
        return f"{base} → 両建てゼロ (要個別確認)"
    return f"{base} → 数量不一致 (注文改定/部分約定の未反映? 個別確認)"


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
