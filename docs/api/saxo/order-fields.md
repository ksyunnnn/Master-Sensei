# Order Fields — GET /port/v1/orders/me

ライブ未約定注文 (open/working orders) の field 定義 (ADR-026)。
`SaxoClient.get_open_orders()` が `OpenOrder` dataclass に意味的展開する。
**`/sync-saxo` の注文ドリフト照合** (`SenseiDB.reconcile_open_orders`) で
ライブ注文 ↔ 判断層 `trades` の placed 申告 (`broker_ref`) を突合する。

- citation: Saxo OpenAPI Reference — Portfolio / Orders (`GET /port/v1/orders/me`)
- 結合キー: **`OrderId`** ↔ `trades.broker_ref` (placed 行)。
  `TradeId`/`PositionId` と混同しない (trade-report-fields.md と同じ規約)
- placed 注文は fill が無いため**台帳照合では出ない**。本 endpoint が唯一の検出源。

## Query parameter

`?FieldGroups=DisplayAndFormat` で `Symbol` を得る (positions と同様)。

## 主要 field (`Data[]` の各要素)

| path | 型 | 意味 | OpenOrder |
|------|----|----|----|
| `OrderId` | str | 注文一意 ID。`broker_ref` と join | `order_id` |
| `AccountId` | str | どの口座か | `account_id` |
| `Uic` | int | instrument 一意 ID | `uic` |
| `Amount` | float | 注文数量 | `amount` |
| `BuySell` | str | `Buy`/`Sell` | `buy_sell` |
| `OpenOrderType` | str | `Limit`/`Stop`/`StopLimit`/`TrailingStop` 等 | `order_type` |
| `Price` | float/null | 指値/逆指値価格 (Market は null) | `price` |
| `Status` | str | `Working` 等 | `status` |
| `DisplayAndFormat.Symbol` | str/null | `SOXL:arcx` 形式。`:` 前を正規化 | `symbol` |

symbol 正規化は position-fields.md と共通 (`_normalize_symbol`)。

## 検証状態

- 本 endpoint の field 名は Saxo OpenAPI Portfolio/Orders 公式仕様に基づく。
  本プロジェクトは read-only で発注しないため、live サンプルは**注文存置時のみ**捕捉可能。
- accessor は required field (`OrderId,AccountId,Uic,Amount,BuySell,OpenOrderType,Status`)
  欠落時に `SaxoAuthError` を投げ、shape 相違を**静かに飲み込まない** (balance accessor と同方針)。
  次回 live で working order を置いたとき実 shape を本書に追記する。
