---
name: sync-saxo
description: Saxoの実約定を執行事実層(Parquet)に全mirror取得し、判断層tradesと照合してbreak(乖離)を検出・修正提案する。DBがずれていないか定期確認に使う。
---

Saxo 照合ワークフローを実行してください (ADR-030)。判断層 `trades`(宣言) と
執行事実層 `account_transactions`(Saxo 由来の実約定) を突合し、乖離(break)を直す。

## タイムゾーン

現在時刻(JST): !`TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M JST'`

## 前提: token

`auth_tokens` の expires_at を確認し、失効していれば **Claude 自身が**
`scripts/saxo_oauth_init.py` をバックグラウンド起動する(ユーザーが担うのはブラウザ
ログインのみ。`! python ...` をユーザーに丸投げしない。CLAUDE.md / ADR-025)。

## 手順

1. **執行事実層を全 mirror 取得** (Saxo reports/trades → Parquet 上書き):
   ```bash
   python scripts/import_account_transactions.py --from-date 2026-01-01
   ```

2. **ポジション照合** (DB申告 vs 台帳実態) を SenseiDB で実行する:
   ```python
   import duckdb
   from pathlib import Path
   from src.db import SenseiDB
   conn = duckdb.connect(str(Path("data/sensei.duckdb")))
   db = SenseiDB(conn)
   breaks = db.reconcile_positions(str(Path("data/parquet/account/transactions.parquet")))
   for b in breaks:
       print(b)  # {instrument, trades_open_qty, ledger_net_qty}
   ```

3. **ライブ状態の照合** (現保有・生きてる注文。台帳=履歴とは別) を取得する:
   ```python
   from src.saxo_client import SaxoClient
   client = SaxoClient(db)
   positions = client.get_positions()                    # 現保有(導出, 都度)
   orders = client._api_get("/port/v1/orders/me").get("Data", [])  # 未約定注文
   ```
   - DB の `get_open_trades()` / `get_pending_orders()` と突合する。
   - 未約定注文の `OrderId` が `trades.broker_ref`(placed行) と一致するか確認する。

4. **break を分類して提示** (ADR-030)。曖昧でない遷移のみ自動修正、曖昧は人間に1件ずつ確認:

   | break | 意味 | 修正 |
   |-------|------|------|
   | trades=建玉中 だが ledger net=0 | クローズ済未反映 | `close_trade()`(exit を台帳の sell fill から) |
   | ledger net>0 だが trades 申告なし | 未記録エントリー | `add_trade(status='filled', broker_ref=OrderId)` |
   | placed の値 ≠ live order | 注文改定未反映 | `set_trade_broker_ref()` / 値更新 or 旧 expired+新規起票 |
   | placed だが対応注文も fill も無い | 不発/失効 | `update_trade_status('expired'/'cancelled')` |

5. **修正は SenseiDB メソッド経由のみ**。物理削除はしない(ADR-018 後知恵バイアス排除)。
   修正後にもう一度 `reconcile_positions()` を実行し、break=0 を確認する。

## 注意

- 入出金(deposit/withdrawal)は別エンドポイント未特定のため本 mirror に含まれない
  (約定のみ)。`docs/api/saxo/trade-report-fields.md` の「未解決」参照。
- 結合キーは **OrderId** (`trades.broker_ref` ↔ `ledger.order_id`)。`TradeId`/`PositionId`
  と混同しない (docs/api/saxo/trade-report-fields.md)。
- ライブ状態(現保有/注文)は保存しない。履歴は `account_transactions`(Parquet) が SoT。
