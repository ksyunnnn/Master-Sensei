# Saxo Historical Report Data - Trades Response Fields

`GET /cs/v1/reports/trades/{ClientKey}` の response。**実約定の不変台帳**（buy/sell の事実）を取得し、`account_transactions`（執行事実層）の供給源にする (ADR-030)。

**出典 (Primary)**: [Saxo Developer Portal - Historical Report Data / Trades](https://www.developer.saxo/openapi/referencedocs/cs/v1/historicalreportdata-trades)

> ⚠️ **検証状態 (ADR-026 / 事実検証3段階)**: 2026-06-03 に live 口座で実呼出して確認した。
> - **endpoint 存在・動作・契約状態**: ✅ HTTP 200（live, ClientKey 指定, FromDate/ToDate 指定）。9件取得。
> - **クエリパラメータ**: ✅ 公式リファレンスで確認。
> - **レスポンス各 field の意味**: 公式スキーマページが JS レンダリングで WebFetch 不能だったため、**下表は live 実データから observed**（実値を併記）。意味を**変数名から推測した箇所には「⚠推測」を明記**。importer で使う前に未確定 field は追加検証する。

## リクエスト

```
GET /cs/v1/reports/trades/{ClientKey}?FromDate={YYYY-MM-DD}&ToDate={YYYY-MM-DD}
```

クエリパラメータ（公式確認済）:

- **`ClientKey`**: client の一意キー（path、必須）。`/port/v1/accounts/me` の `ClientKey`。※ `ClientId`（数値）とは別物
- **`FromDate` / `ToDate`**: 取得期間（trade date 基準）
- **`AccountKey` / `AccountGroupKey`**: 口座/グループで絞り込み（任意）
- **`TradeId`**: 特定 trade で絞り込み（任意）
- **`$top` / `$skip` / `$skiptoken`**: ページング

レスポンス top-level: `{ "__count": <int>, "Data": [ ... ] }`

## レスポンス Data[] の field（observed, 2026-06-03 live）

実例2件（SOXL、trade 12 に対応する往復）:

| TradeId | OrderId | InstrumentSymbol | Amount | Price | ToOpenOrClose | TradeEventType | TradeType | TradeDate | ValueDate | TradeExecutionTime | BookedAmountUSD | BookedAmountAccountCurrency |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 6732724591 | 5409009626 | SOXL:arcx | 3.0 | 218.0 | ToOpen | Bought | Limit | 2026-06-01 | 2026-06-02 | 2026-06-01T13:51:47.737Z | -655.77 | -104712 |
| 6734709190 | 5409035181 | SOXL:arcx | -3.0 | 243.18 | ToOpen | Sold | Limit | 2026-06-02 | 2026-06-03 | 2026-06-02T13:30:00.233Z | 727.05 | 116283 |

### 結合キー（ID 体系は3つ。混同禁止）

Saxo には**別名前空間の ID が3系統**ある。照合の結合キーは **`OrderId`** に統一する（`orders/me` と `reports/trades` の両方が持つ唯一の共通キー）:

| ID | 出どころ | 粒度 | 用途 |
|----|---------|------|------|
| **`OrderId`** | `orders/me`, `reports/trades` | 1注文 | **`trades.broker_ref` = これ**（判断/宣言 → 注文の結合キー） |
| **`TradeId`** | `reports/trades` | 1約定（部分約定ごと） | `account_transactions` の主キー。1 OrderId が複数 TradeId を生む |
| **`PositionId`** (Opening/Closing) | `positions/me`, `closedpositions/me` | 1ポジション | ポジション照合用。`OrderId`/`TradeId` とは別物。**broker_ref に使わない** |

### 主要 field の意味

| field | 意味 | 確証 |
|-------|------|------|
| `TradeId` | 約定（fill）の一意 ID | observed（一意・約定単位） |
| `OrderId` | この約定を生んだ注文の ID | observed（`orders/me`/decision と一致） |
| `AccountId` | 口座（"77800/T126816"） | observed |
| `Uic` | instrument 一意 ID（SOXL=46780） | 既知（endpoints.md） |
| `InstrumentSymbol` | "SYMBOL:exchange" 形式（"SOXL:arcx"） | observed |
| `AssetType` | "Etf" 等 | observed |
| `Amount` | **符号付数量。正=買, 負=売** | observed（`TradeEventType` と整合: +3↔Bought, −3↔Sold） |
| `Price` | 約定単価（instrument 通貨） | observed |
| `TradeEventType` | **"Bought" / "Sold"**。買売判定はこれを使う | observed |
| `Direction` | observed では "None" を返す。**買売判定に使わない** | observed（"None"のため非採用） |
| `ToOpenOrClose` | "ToOpen" / "ToClose" | observed（※両建で意味、本実例は両方 ToOpen） |
| `TradeType` | 注文種別（"Limit" 等） | observed |
| `TradeDate` | 約定日 | observed |
| `ValueDate` | **受渡日（settlement）**。本実例 T+1 | observed（TD 6/1 → VD 6/2） |
| `AdjustedTradeDate` | 調整後 trade date | observed |
| `TradeExecutionTime` | 約定時刻（UTC, ISO8601） | observed |
| `BookedAmountUSD` | **記帳額 USD。買=負(cash out), 売=正(cash in)** | observed |
| `BookedAmountAccountCurrency` | 記帳額（口座通貨=JPY） | observed |
| `BookedAmountClientCurrency` | 記帳額（client 通貨=JPY） | observed |
| `SpreadCostUSD` / `SpreadCostAccountCurrency` | spread コスト | observed（本実例 0.0） |
| `Venue` / `ExchangeDescription` | 取引所 | observed |
| `InstrumentDescription` | 銘柄正式名 | observed |

> **⚠推測 / 未確定**: `ToOpenOrClose` が売り(−3)でも "ToOpen" を返した理由（netting 口座の挙動か）、`FinancingLevel`/`ResidualValue`/`ToolId`/`TradeBarrierEventStatus` の意味は未確定。importer では**使う field のみ**意味的アクセサに載せ、未使用 field は raw に残さない（ADR-026）。

## account_transactions へのマッピング（ADR-015 スキーマ）

| account_transactions | ← reports/trades |
|------|------|
| `trade_date` | `TradeDate` |
| `settlement_date` | `ValueDate` |
| `type` | `TradeEventType`（Bought→buy / Sold→sell） |
| `instrument` | `InstrumentSymbol` の symbol 部 or `Uic` 逆引き |
| `quantity` | `abs(Amount)` |
| `price_per_unit` | `Price` |
| `amount` | `BookedAmountUSD`（currency=USD 時） |
| `amount_jpy` | `BookedAmountAccountCurrency` |
| `broker_ref` | **`TradeId`**（台帳の主キー） |
| （decision 結合用）| `OrderId` → `trades.broker_ref` と join |

## 解決済（後続）

- **入出金（deposit/withdrawal）**: `/cs/v1/reports/bookings/{ClientKey}` の `AssetType='Cash'` 行で取得（ADR-030 Phase 5、2026-06-03 live 検証）。フィールド定義は [booking-fields.md](booking-fields.md)。`accountStatement` は PDF/XLS 用で JSON 不可だったため不使用。
