"""執行事実層 account_transactions (Parquet) の構築 (ADR-030 / ADR-015)。

Saxo `reports/trades` の実約定 (TradeReport) を、口座取引台帳の行へ写像する。
台帳は Saxo を SoT とする **全 mirror** で運用し、価格/マクロ同様に再取得 →
上書きする (ADR-001/009)。`trades`(判断層) とは `order_id` ↔ `trades.broker_ref`
で照合する。

ID 体系 (docs/api/saxo/trade-report-fields.md):
- `broker_ref` = TradeId (約定=fill の主キー。ADR-015 の "Saxo 取引ID")
- `order_id`   = OrderId (注文。`trades.broker_ref` との結合キー)

入出金・現金移動 (deposit/withdrawal) は `reports/bookings` の `AssetType='Cash'` 行を
`cash_bookings_to_rows` で写像する (ADR-030 Phase 5、docs/api/saxo/booking-fields.md)。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from src.saxo_client import CashBooking, TradeReport

# ADR-015 のスキーマ + ADR-009(source/updated_at) + 3ID 体系対応(order_id/account_id)。
ACCOUNT_TX_COLUMNS = [
    "trade_date",        # 約定日
    "settlement_date",   # 受渡日 (ValueDate)
    "type",              # buy / sell / deposit / withdrawal
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


def cash_bookings_to_rows(
    bookings: list[CashBooking], *, source: str, updated_at: datetime,
) -> list[dict]:
    """CashBooking のリストを account_transactions 行 (dict) のリストに写像する。

    入出金・現金移動 (ADR-030 Phase 5)。純関数。

    - type: `amount_usd >= 0 → 'deposit'`、`< 0 → 'withdrawal'`。口座間振替の「入」も
      この取引口座にとっては資金供給 (cash in) なので機能的に deposit。元の性質は
      `instrument` に symbol (例 CASHINTRTP) を保持して可逆にする (symbol へのハード
      コード禁止: 外部入出金の symbol は未観測のため向きは符号で判定)。
    - quantity / price_per_unit: 現金行は株数・単価を持たない → None。
    - broker_ref: BkAmountId (現金行の主キー)。order_id: 注文を伴わない → None。
    """
    rows: list[dict] = []
    for b in bookings:
        usd = b.amount_usd
        fx_rate = abs(b.amount_account_currency / usd) if usd else None
        rows.append({
            "trade_date": b.date,
            "settlement_date": b.value_date,
            "type": "deposit" if usd >= 0 else "withdrawal",
            "instrument": b.symbol,
            "quantity": None,
            "price_per_unit": None,
            "amount": usd,
            "currency": "USD",
            "fx_rate": fx_rate,
            "amount_jpy": b.amount_account_currency,
            "realized_pnl": None,
            "broker_ref": b.booking_id,
            "order_id": None,
            "account_id": b.account_id,
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


# 口座開設以降を広く取る (Saxo の遡及制限内)。テール窓が使えない初回 mirror の起点。
DEFAULT_FROM_DATE = "2026-01-01"
# 遡及訂正・遅延記帳 (T+1 決済 + 週末 + 祝日) を拾う窓の余裕 (ADR-030)。
DEFAULT_OVERLAP_DAYS = 7


def latest_trade_date(path: Path) -> Optional[date]:
    """既存 parquet の最大 trade_date を返す。ファイルが無ければ None。

    テール窓 mirror の anchor。None なら full mirror に倒す (window_from_date)。
    """
    if not path.exists():
        return None
    import duckdb

    row = duckdb.sql(
        f"SELECT max(trade_date) FROM read_parquet('{path}')"
    ).fetchone()
    if row is None or row[0] is None:
        return None
    value = row[0]
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def window_from_date(
    latest: Optional[date], *, overlap_days: int, default_from: str
) -> str:
    """テール窓 mirror の from_date ("YYYY-MM-DD") を決める純関数 (ADR-030)。

    - latest=None (parquet 無し) → full mirror の default_from。
    - latest あり → anchor(=最新trade_date) から overlap_days 引いた日付。
      anchor 自体が「前回 sync 以降」を保証し、overlap は既取り込み行への
      遡及訂正 (決済サイクル等) を拾う保険。upsert なので広めでも無料。
    """
    if latest is None:
        return default_from
    return (latest - timedelta(days=overlap_days)).isoformat()


def merge_transactions_parquet(rows: list[dict], path: Path) -> int:
    """台帳行を **broker_ref で upsert マージ** し、総行数を返す (ADR-030)。

    全置換 (write_transactions_parquet) と違い、既存 parquet を保持したまま
    新規行を足し、同一 broker_ref (TradeId/BkAmountId=不変主キー) は新しい値で
    上書きする。テール窓で既出行を再取得しても冪等 = 重複も破損もしない。
    既存ファイルは .bak に退避する。
    """
    import shutil

    import pandas as pd

    new_df = pd.DataFrame(rows, columns=ACCOUNT_TX_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(".parquet.bak"))
        existing = pd.read_parquet(path, engine="pyarrow")
        if new_df.empty:
            combined = existing  # 窓内に新規ゼロ件: 既存をそのまま保持
        else:
            combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df
    # 新しい方を残す: concat で new_df を後ろに置き keep='last'。
    combined = combined.drop_duplicates(subset="broker_ref", keep="last")
    combined = combined.sort_values("trade_date").reset_index(drop=True)
    combined.to_parquet(path, engine="pyarrow", index=False)
    return len(combined)


def explain_ledger_surplus_by_closed_positions(
    live_breaks: list[dict],
    closed_positions: list,
) -> tuple[list[dict], list[dict]]:
    """live建玉↔台帳 の break を、決済済ポジションで説明できるか判定する (ADR-030)。

    **なぜ要るか**: 執行事実層 `account_transactions` の供給源 `reports/trades` は
    booking が T+1 のため、決済当日は台帳に sell 行が入らない。その結果
    「ライブ建玉=0 / 台帳net=24」を `reconcile_live_positions` が**真の乖離と誤報**する
    (2026-08-19 の SOXL 24株決済で実際に誤報し、照合が前に進まなくなった)。
    `closedpositions` は同じ Saxo 由来でありながら決済当日に読めるので、
    その差分を「booking 待ち (benign)」と説明できる。

    Args:
        live_breaks: `SenseiDB.reconcile_live_positions()` の返り値。各要素は
            `{"instrument", "live_net_qty", "ledger_net_qty"}`。
        closed_positions: `SaxoClient.get_closed_positions()` の返り値
            (`ClosedPosition` のリスト)。`signed_amount()` が台帳 net への寄与を
            符号付きで返す (買い建ての決済 = sell 行 = 負)。

    Returns:
        `(unexplained, explained)` のタプル。
        - `unexplained`: 説明できず人間の確認が要る break (入力と同じ dict 形式)。
        - `explained`: booking 待ちと判定した break に
          `{"closed_qty": <決済数量の絶対値>}` を添えた dict のリスト。

    設計上の制約:
        `closedpositions` は `OrderId` を返さないため個々の `trades` 行と 1対1 結合
        できない。判定は **instrument 単位の数量合計**に留める
        (docs/api/saxo/closed-position-fields.md の「罠2」)。
    """
    # instrument ごとに「booking が届いたら台帳 net はどこへ動くか」を先取りする。
    closed_by_symbol: dict[str, list] = {}
    for cp in closed_positions:
        closed_by_symbol.setdefault(cp.symbol, []).append(cp)

    unexplained: list[dict] = []
    explained: list[dict] = []
    for b in live_breaks:
        cps = closed_by_symbol.get(b["instrument"], [])
        projected = b["ledger_net_qty"] + sum(cp.signed_amount() for cp in cps)
        # 反映後の台帳がライブ建玉と過不足なく一致した時だけ benign にする。
        # 部分一致を許すと booking 待ちに紛れた真の乖離を握り潰すため。
        if cps and abs(projected - b["live_net_qty"]) < 1e-9:
            explained.append({**b, "closed_qty": sum(cp.amount for cp in cps)})
        else:
            unexplained.append(b)
    return unexplained, explained
