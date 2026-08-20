# Order Fields — GET /port/v1/orders/me

ライブ未約定注文 (open/working orders) の field 定義 (ADR-026)。
`SaxoClient.get_open_orders()` が `OpenOrder` dataclass に意味的展開する。
**`/sync-saxo` の注文ドリフト照合** (`SenseiDB.reconcile_open_orders`) で
ライブ注文 ↔ 判断層 `trades` の placed 申告 (`broker_ref`) を突合する。

- citation: Saxo OpenAPI Reference — Portfolio / Orders (`GET /port/v1/orders/me`)
- 結合キー: **`OrderId`** ↔ `trades.broker_ref` (placed 行)。
  `TradeId`/`PositionId` と混同しない (trade-report-fields.md と同じ規約)
- placed 注文は fill が無いため**台帳照合では出ない**。本 endpoint が唯一の検出源。
- **保護脚は親の `RelatedOpenOrders[]` にネストされる**。`SaxoClient.get_open_orders()` は
  親と脚を平坦化して返す（issue#16、下記「アクセサの扱い」）

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

## 関連注文 (IFD-OCO) は `RelatedOpenOrders` にネストされる

🔬 2026-07-28 実測。IFD-OCO を発注すると、**親注文だけが `Data[]` のトップレベルに現れ、
保護脚 (決済指値 / 決済逆指値) は親の `RelatedOpenOrders[]` 配下に入る**。


### アクセサの扱い（issue#16 で修正）

`get_open_orders()` は `Data[]` のトップレベルと `RelatedOpenOrders[]` の両方を走査し、
**親と脚を平坦化した1本のリスト**で返す。トップレベルだけ見ると stop/TP が返り値に現れず、
**保護の付いていない建玉と誤読する**（2026-07-28 に実際に誤読しかけた）。

脚の `OpenOrder` は次のように埋まる。

| field | 由来 |
|---|---|
| `order_id` | 脚の `OrderId`（必須。欠落は `SaxoAuthError`） |
| `price` | 脚の **`OrderPrice`**（`Price` ではない） |
| `order_type` / `status` | 脚の `OpenOrderType` / `Status` |
| `parent_order_id` | 親の `OrderId`（脚であることの識別子） |
| `order_relation` | `IfDoneMaster` / `Oco` 等 |
| `symbol` / `account_id` / `uic` / `amount` | **親から引き継ぐ**（同一銘柄・同一口座の決済注文なので構造的に同じ） |
| `buy_sell` | 脚に `BuySell` が無ければ **`None`**。向きを推測しない（ADR-026） |

```
Data[0]  OrderId=5428389110  BuySell=Buy  OpenOrderType=Limit  Price=95.0
         OrderRelation="IfDoneMaster"  Status="Working"
  └ RelatedOpenOrders[0]  OrderId=5428389111  OpenOrderType=Limit
                          OrderPrice=136.0  Status="NotWorking"
  └ RelatedOpenOrders[1]  OrderId=5428389112  OpenOrderType=StopIfTraded
                          OrderPrice=89.0  Status="NotWorking"
```

- 保護脚の価格 field は `Price` ではなく **`OrderPrice`**。
- 親が未約定の間、保護脚の `Status` は **`NotWorking`**。親が約定すると保護脚は
  トップレベルへ昇格し、`OrderRelation="Oco"` の相互参照ペア (互いを
  `RelatedOpenOrders` に持つ) として `Status="Working"` になる。
- ⚠ `SaxoClient.get_open_orders()` は `Data[]` のトップレベルのみ走査するため、
  **親未約定の保護脚を取りこぼす**。「建玉に stop が付いていない」と誤読しうる。

## 関連注文の距離制限 (発注拒否の原因)

🔬 2026-07-06 / 2026-07-28 実測。保護脚の価格が親注文価格から離れすぎていると、
発注が拒否される。エラー文言は「注文価格は、入力注文よりも差がありすぎます」で、
**距離超過した脚が名指しされ**、もう一方の脚は
`Order not placed as other order in request was rejected` として巻き添えで失敗する
(IFD-OCO は脚が全部通らないと成立しない)。

決済指値 (TP) 側の実測値 — 距離は**親注文価格に対する比率**:

| 親価格 | TP | 距離 | 結果 |
|--------|-----|------|------|
| $196 | $250 | +27.6% | 通過 |
| $95 | $120 | +26.3% | 通過 |
| $107 | $136 | +27.1% | 通過 |
| $101 | $136 | +34.7% | 通過 |
| **$95** | **$136** | **+43.2%** | **通過** |
| $95 | $145 | +52.6% | **拒否** |

→ **閾値は +43.2% と +52.6% の間**。未確定なので、確実に通したい場合は
**+40% 以内**に収める。逆指値 (stop) 側は -49.0% ($196→$100) が通っており、
上下で非対称の可能性がある (stop 側の拒否例は未取得)。

**設計上の含意**: 深い押し目ラダーでは、深い段ほど TP までの距離%が大きくなり
制限に当たりやすい。TP をチャートのレベルで揃えると、最も深い段が拒否される。
段ごとに TP をずらすか、全段が通る水準に揃えるかを発注前に検算する。

## 検証状態

- 本 endpoint の field 名は Saxo OpenAPI Portfolio/Orders 公式仕様に基づく。
  本プロジェクトは read-only で発注しないため、live サンプルは**注文存置時のみ**捕捉可能。
- accessor は required field (`OrderId,AccountId,Uic,Amount,BuySell,OpenOrderType,Status`)
  欠落時に `SaxoAuthError` を投げ、shape 相違を**静かに飲み込まない** (balance accessor と同方針)。
  次回 live で working order を置いたとき実 shape を本書に追記する。
