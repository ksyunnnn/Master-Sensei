"""執行事実層 account_transactions (Parquet) の構築 (ADR-030 / ADR-015)。

Saxo `reports/trades` の実約定 (TradeReport) を、口座取引台帳の行へ写像する。
台帳は Saxo を SoT とする **全 mirror** で運用し、価格/マクロ同様に再取得 →
上書きする (ADR-001/009)。`trades`(判断層) とは `order_id` ↔ `trades.broker_ref`
で照合する。

ID 体系 (docs/api/saxo/trade-report-fields.md):
- `broker_ref` = TradeId (約定=fill の主キー。ADR-015 の "Saxo 取引ID")
- `order_id`   = OrderId (注文。`trades.broker_ref` との結合キー)

入出金 (deposit/withdrawal) は別エンドポイント (未特定) のため本写像には含まない。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from src.saxo_client import TradeReport

# ADR-015 のスキーマ + ADR-009(source/updated_at) + 3ID 体系対応(order_id/account_id)。
ACCOUNT_TX_COLUMNS = [
    "trade_date",        # 約定日
    "settlement_date",   # 受渡日 (ValueDate)
    "type",              # buy / sell (将来 deposit / withdrawal)
    "instrument",        # 銘柄コード (例 SOXL)
    "quantity",          # 数量 (常に正)
    "price_per_unit",    # 約定単価
    "amount",            # 記帳額 (買=負/cash out, 売=正/cash in)
    "currency",          # 記帳額の通貨 (約定は USD)
    "fx_rate",           # |JPY/USD| (nullable)
    "amount_jpy",        # 円換算記帳額 (BookedAmountAccountCurrency)
    "realized_pnl",      # 実現損益 (reports/trades は持たない → None)
    "broker_ref",        # TradeId (fill 主キー)
    "order_id",          # OrderId (trades.broker_ref との結合キー)
    "account_id",        # 口座 (77800/T126816 等)
    "source",            # 取り込み元
    "updated_at",        # 取り込み日時
]


def trade_reports_to_rows(
    reports: list[TradeReport], *, source: str, updated_at: datetime,
) -> list[dict]:
    """TradeReport のリストを account_transactions 行 (dict) のリストに写像する。

    純関数。Parquet 書き込みからは独立にテストできる。
    """
    rows: list[dict] = []
    for r in reports:
        usd = r.booked_amount_usd
        fx_rate = abs(r.booked_amount_account_currency / usd) if usd else None
        rows.append({
            "trade_date": r.trade_date,
            "settlement_date": r.value_date,
            "type": r.side,
            "instrument": r.instrument_symbol.split(":")[0],
            "quantity": r.quantity,
            "price_per_unit": r.price,
            "amount": usd,
            "currency": "USD",
            "fx_rate": fx_rate,
            "amount_jpy": r.booked_amount_account_currency,
            "realized_pnl": None,
            "broker_ref": r.trade_id,
            "order_id": r.order_id,
            "account_id": r.account_id,
            "source": source,
            "updated_at": updated_at,
        })
    return rows


def write_transactions_parquet(rows: list[dict], path: Path) -> int:
    """台帳行を Parquet に **全置換 mirror** で書き出す。書き込んだ行数を返す。

    既存ファイルは .bak に退避してから上書きする (CacheManager と同方針)。
    pandas/pyarrow 依存はこの関数に閉じ込め、写像ロジック(純関数)と分離する。
    """
    import shutil

    import pandas as pd

    df = pd.DataFrame(rows, columns=ACCOUNT_TX_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(".parquet.bak"))
    df.to_parquet(path, engine="pyarrow", index=False)
    return len(df)
