"""Saxo 実約定 + 現金移動 → 執行事実層 account_transactions(Parquet) の取り込み (ADR-030)。

Saxo `reports/trades`(約定) と `reports/bookings` の `AssetType='Cash'` 行(入出金・現金移動)を
**全 mirror** 取得し、`data/parquet/account/transactions.parquet` に上書きする。価格/マクロと
同じ「再取得 → 上書き」運用 (ADR-001/009)。`trades`(判断層) とは `order_id` ↔
`trades.broker_ref` で照合する (scripts/sync は別途)。

実行: python scripts/import_account_transactions.py [--from-date YYYY-MM-DD] [--to-date YYYY-MM-DD]

token 失効時は scripts/saxo_oauth_init.py で再認証してから実行する。
入出金は bookings 由来 (ADR-030 Phase 5、docs/api/saxo/booking-fields.md)。
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.account_ledger import (
    cash_bookings_to_rows,
    trade_reports_to_rows,
    write_transactions_parquet,
)
from src.db import SenseiDB, now_jst, today_jst
from src.saxo_client import SaxoAuthError, SaxoClient

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "sensei.duckdb"
PARQUET_PATH = Path(__file__).parent.parent / "data" / "parquet" / "account" / "transactions.parquet"
DEFAULT_FROM = "2026-01-01"  # 口座開設以降を広く取る (Saxo の遡及制限内)


def run_import(from_date: str, to_date: str) -> int:
    conn = duckdb.connect(str(DB_PATH))
    try:
        db = SenseiDB(conn)
        client = SaxoClient(db)
        client_keys = sorted({a["ClientKey"] for a in client.get_accounts()})
        all_rows = []
        updated_at = now_jst()
        for ck in client_keys:
            reports = client.get_trade_reports(
                client_key=ck, from_date=from_date, to_date=to_date,
            )
            rows = trade_reports_to_rows(
                reports, source="saxo_reports_trades", updated_at=updated_at,
            )
            all_rows.extend(rows)

            bookings = client.get_bookings(
                client_key=ck, from_date=from_date, to_date=to_date,
            )
            cash_rows = cash_bookings_to_rows(
                bookings, source="saxo_reports_bookings", updated_at=updated_at,
            )
            all_rows.extend(cash_rows)
            logger.info("ClientKey %s: %d fills, %d cash movements",
                        ck, len(rows), len(cash_rows))
        n = write_transactions_parquet(all_rows, PARQUET_PATH)
        logger.info("Wrote %d rows → %s", n, PARQUET_PATH)
        return n
    finally:
        conn.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Saxo 実約定 → account_transactions(Parquet)")
    parser.add_argument("--from-date", default=DEFAULT_FROM, help="開始日 YYYY-MM-DD")
    parser.add_argument("--to-date", default=str(today_jst()), help="終了日 YYYY-MM-DD")
    args = parser.parse_args()
    try:
        run_import(args.from_date, args.to_date)
    except SaxoAuthError as e:
        print(f"[import-account-transactions] AUTH ERROR: {e}", file=sys.stderr)
        print("→ python scripts/saxo_oauth_init.py で再認証してから再実行", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
