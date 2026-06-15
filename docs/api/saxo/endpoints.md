# Saxo OpenAPI 使用 endpoints

base URL (Live): `https://gateway.saxobank.com/openapi`
base URL (SIM): `https://gateway.saxobank.com/sim/openapi`

公式: https://www.developer.saxo/openapi/learn/environments

## 認証

全 endpoint は `Authorization: Bearer <access_token>` 必須。
access token 取得は ADR-025 (OAuth 2.0 Authorization Code grant) 参照。

## 使用 endpoint 一覧

### 1. GET /port/v1/accounts/me

ログイン中ユーザの全 sub-account を取得。

- 公式: https://www.developer.saxo/openapi/referencedocs/port/v1/accounts
- code: `SaxoClient.get_accounts()`
- 返り値: `Data` 配列 (各要素が account dict)

**実例レスポンス** (2026-05-26 取得、PII 部分マスク):
```json
{
  "Data": [
    {
      "AccountId": "77800/P120136",
      "AccountKey": "9SdaOVfmGO3Se0gt1q3N...",
      "ClientKey": "...",
      "Currency": "JPY",
      "Active": true
    },
    {"AccountId": "77800/T126816", "Currency": "JPY", "Active": true},
    {"AccountId": "77800/N122798", "Currency": "USD", "Active": true},
    ...
  ]
}
```

- 主要 field: `AccountId`, `AccountKey`, `ClientKey`, `Currency`, `Active`
- 注意: `AccountKey` は API call で必須の identifier。`AccountId` は人間可読 (口座番号)

### 2. GET /port/v1/balances/me

ログイン中ユーザの **aggregated** balance (全 sub-account 合算、base currency 換算)。

- 公式: https://www.developer.saxo/openapi/referencedocs/port/v1/balances
- code: `SaxoClient.get_balances()`
- 返り値: 1個の balance dict (全 field は [balance-fields.md](balance-fields.md))

**本プロジェクトでの推奨**: 口座別が必要なので endpoint #3 を使うこと。`/me` の aggregate は USD/JPY 混在で解釈困難 (2026-05-26 観測: CashBalance=37,117 JPY と全 JPY 口座合計 125,000 JPY が乖離 — JPY base に集約された結果と推測されるが詳細未確認)

### 3. GET /port/v1/balances?AccountKey={key}&ClientKey={key}

**口座別 balance** を取得。

- code: `SaxoClient._api_get(f"/port/v1/balances?AccountKey={k}&ClientKey={c}")` (内部 method 経由)
- 返り値: 1個の balance dict (口座固有)

**実例レスポンス** (2026-05-26 P120136、SOXL 1株保有):
```json
{
  "CalculationReliability": "Ok",
  "CashAvailableForTrading": 21901.0,
  "CashBalance": 21901.0,
  "CashBlocked": 0.0,
  "Currency": "JPY",
  "NetEquityForMargin": 21901.0,
  "NetPositionsCount": 1,
  "NonMarginPositionsValue": 30251.61,
  "OpenPositionsCount": 1,
  "SpendingPower": 21901.0,
  "TotalValue": 52152.61,
  "TransactionsNotBooked": 0.0,
  "UnrealizedPositionsValue": 30075.0
}
```

**実例レスポンス** (2026-05-26 T126816、5/22 SOXL 売却 T+2 settling 中):
```json
{
  "CashBalance": 15216.61,           // 注: settled only、sizing には使わない
  "CashAvailableForTrading": 103099.0,  // ← sizing にはこれを使う
  "SpendingPower": 103099.0,            // ← 同値
  "TransactionsNotBooked": 87882.39,    // ← 5/22 SOXL 売却の T+2 未決済分
  "TotalValue": 103099.0,
  ...
}
```

### 4. GET /port/v1/positions/me

open positions のリスト。

- code: `SaxoClient.get_positions()` (内部で `Data` 配列を返す)
- 返り値: position dict のリスト

**主要 field**:
- `PositionBase.AccountId`: どの口座のポジションか
- `PositionBase.Uic`: instrument の一意 ID (e.g., SOXL = 46780)
- `PositionBase.Amount`: 数量 (正=long、負=short)
- `PositionBase.OpenPrice`: entry price
- `PositionView.CurrentPrice`: 現在価格 (米市場休場中は 0)
- `PositionView.MarketValue`: 市場評価額 (米市場休場中は 0)
- `PositionView.ProfitLossOnTradeInBaseCurrency`: 含み損益 (base currency = JPY)

**実例レスポンス** (2026-05-26、P120136 の SOXL 1株):
```json
{
  "PositionBase": {
    "AccountId": "77800/P120136",
    "Uic": 46780,
    "Amount": 1.0,
    "OpenPrice": 176.0
  },
  "PositionView": {
    "CurrentPrice": 0.0,           // 米市場休場のため 0
    "MarketValue": 0.0,
    "ProfitLossOnTradeInBaseCurrency": 2342.0  // ≒ +$14.76 (FX 158.67)
  },
  "DisplayAndFormat": {
    "Description": null,           // FieldGroup パラメタなしのため null
    "Symbol": null
  }
}
```

**注意**:
- `DisplayAndFormat` の中身を取得するには `?FieldGroups=DisplayAndFormat,PositionView` 等の query parameter が必要。本プロジェクトはまだ未対応 (Uic から symbol 逆引きが必要なら別途実装)
- 米市場休場中の `CurrentPrice` = 0 問題: Parquet の close price で代替

## token endpoint (OAuth 用、Portfolio とは別)

### POST https://live.logonvalidation.net/token

- 用途: code 交換 + token refresh
- code 実装: `SaxoClient.exchange_code_for_tokens()`, `SaxoClient._refresh_access_token()`
- **token lifetime / refresh ローリング / app依存の詳細は `token-auth.md`**(ADR-025/026)
- keepalive(失効直前 backstop): `scripts/saxo_keepalive.py`
- ADR-025 参照

## Historical Report Data (ADR-030, 執行事実層の供給源)

### GET /cs/v1/reports/trades/{ClientKey}

実約定の不変台帳（buy/sell）。`account_transactions`（Parquet）の供給源。

- 検証: 2026-06-03 live で HTTP 200 確認（ADR-026 / 事実検証3段階クリア）
- フィールド定義: [trade-report-fields.md](trade-report-fields.md)
- 結合キー: **`OrderId`**（`trades.broker_ref` と join）、約定主キー `TradeId`
- 買売判定: `TradeEventType`（"Bought"/"Sold"）。`Direction` は "None" で使えない

### GET /cs/v1/reports/bookings/{ClientKey}

記帳＝全勘定エントリー（約定の内訳＋現金移動＋手数料内訳）。`account_transactions` の
**入出金・現金移動（deposit/withdrawal）行**の供給源（ADR-030 Phase 5）。

- 検証: 2026-06-03 live で HTTP 200 確認（108 行）
- フィールド定義: [booking-fields.md](booking-fields.md)
- 取り込みは **`AssetType='Cash'` 行のみ**（ETF 行は約定内訳で reports/trades と二重計上になるため除外）
- code: `SaxoClient.get_bookings()` → `CashBooking`
- query: `FromDate`/`ToDate`（trades と同形）

## 未使用 / 未特定 endpoint (将来検討)

- `/trade/v1/orders/me`: 発注 (本プロジェクトは read-only、未使用)
- `/trade/v1/prices/`: リアルタイム価格 (米市場休場対策で将来検討)
- `/port/v1/orders/me`: 未約定注文一覧（照合で使用、意味的アクセサ未整備）
- `/port/v1/closedpositions/me`: クローズ済 position 履歴（照合で使用）
- `/cs/v1/audit/orderactivities/me`: 取引履歴 audit
- `/cs/v1/reports/accountStatement/{ClientKey}`: 404（PDF/XLS 用レポートで JSON 不可）。入出金は **`/cs/v1/reports/bookings/` で解決済**（上記、ADR-030 Phase 5）
