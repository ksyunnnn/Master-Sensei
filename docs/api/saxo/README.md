# Saxo OpenAPI リファレンス

## 概要

- **公式 doc**: https://www.developer.saxo/openapi/learn/
- **reference docs**: https://www.developer.saxo/openapi/referencedocs
- **code module**: `src/saxo_client.py`
- **認証方式**: OAuth 2.0 (Authorization Code grant、ADR-025)
- **rate limit**: アプリ全体 1,000万 req/日、セッション×サービスグループ 120 req/分 ([rate-limits.md](rate-limits.md))
- **本プロジェクトでの用途**: Live 口座 (P120136 等 7 sub-accounts) の現金残高・open positions 取得

## ファイル

| ファイル | 内容 |
|---------|------|
| README.md | 本ファイル |
| [balance-fields.md](balance-fields.md) | Balance response の全 field 公式定義 (citation 必須) |
| [cash-account-constraints.md](cash-account-constraints.md) | 現金口座の取引制約 (同一銘柄同日ロック・買い指値は現金非予約・MODIFY可) 検証済/未検証 |
| [cost-fields.md](cost-fields.md) | Trade cost response の全 field 公式定義 = break-even 判定 (ADR-029) |
| [fee-schedule.md](fee-schedule.md) | 公式手数料体系 (commission/為替/カストディ) の普遍的事実 + citation |
| [endpoints.md](endpoints.md) | 使用 endpoint + 実例レスポンス |
| [token-auth.md](token-auth.md) | OAuth token lifetime / refresh ローリング / app依存・keepalive (ADR-025/026) |
| [trade-report-fields.md](trade-report-fields.md) | 約定レポートの全 field 公式定義 (結合キー OrderId、ADR-030) |
| [booking-fields.md](booking-fields.md) | bookings (入出金/現金移動) の全 field 公式定義 (ADR-030 Phase5) |
| [rate-limits.md](rate-limits.md) | rate limit 公式値 |

## 用途別 field 早見表

**重要**: 解釈前に必ず balance-fields.md を参照 (ADR-026)。

| 用途 | 使う field | 使ってはいけない field | 理由 |
|------|----------|--------------------|------|
| **新規取引の sizing (今夜 SOXL 何株買えるか)** | `CashAvailableForTrading` または `SpendingPower` | `CashBalance` | CashBalance は settled cash のみ。未決済分 (TransactionsNotBooked) を含まないため過小評価する |
| 口座評価額 (NAV) | `TotalValue` | `CashBalance` | TotalValue = cash + 未実現ポジション評価額 |
| 含み損益確認 | position 側の `ProfitLossOnTradeInBaseCurrency` (為替変動を含まない) か現値から自前計算 (K-048) | `UnrealizedPositionsValue` | UnrealizedPositionsValue は「時価 − 決済コスト」で含み損益ではない。2026-09-01 実測で +449,931 円 vs 実際の含み損益 -28,200 円 |
| 建玉の時価 | `NonMarginPositionsValue` | `UnrealizedPositionsValue` | 決済コストが引かれているぶんずれる |
| margin 必要量算出 | `NetEquityForMargin` | `TotalValue` | NetEquityForMargin が margin 計算の正式 base |
| margin 余力確認 | `MarginAvailableForTrading` | `CashAvailableForTrading` | margin instrument (CFD/FX) では別の field |

## 意味的アクセサ (src/saxo_client.py)

残高は **per-field のメソッドではなく、`AccountBalance` dataclass を返す1メソッド**で取る
(ADR-026)。field は dataclass の属性としてアクセスする (raw dict access 禁止)。

| メソッド | 返り値 | 用途 |
|---------|--------|------|
| `get_all_account_balances()` | `list[AccountBalance]` (active 口座のみ) | 全口座の残高を一括取得 |
| `get_account_balance(*, account_key, client_key, account_id="")` | `AccountBalance` | 単一口座の残高 |
| `get_balances()` (raw dict) | 集計 balance | 調査用途のみ (sizing に使わない) |

`AccountBalance` の属性 (公式定義は balance-fields.md):

| 属性 | 元 Saxo field | 用途 |
|------|--------------|------|
| `spending_power` | `SpendingPower` | **sizing 判断 (これを使う)** |
| `cash_available_for_trading` | `CashAvailableForTrading` | sizing 判断 (SpendingPower と同値、互換) |
| `settled_cash_balance` | `CashBalance` | 会計表示用 (**sizing には使わない**、未決済除外で過小評価) |
| `total_value` | `TotalValue` | NAV |
| `unrealized_positions_value` | `UnrealizedPositionsValue` | 建玉の時価 − 決済コスト (**含み損益ではない**) |
| `transactions_not_booked` | `TransactionsNotBooked` | T+2 未決済額 (debug 用) |
| `open_positions_count` / `net_positions_count` | 同名 | open / (open+settling) 建玉数 |
| `non_margin_positions_value` | `NonMarginPositionsValue` | cash instrument 評価額合計 |
| `calculation_reliability` | `CalculationReliability` | "Ok" 以外は要調査 |

> **MCP 経由 (ADR-035)**: Claude は上記を手書きせず、`master-sensei-live` MCP サーバの
> `get_account_balances` ツールで named-field JSON として取得する。sizing は `spending_power`。

## 既知の落とし穴

### CashBalance vs CashAvailableForTrading vs SpendingPower

3つとも英語名が似ているが意味が違う。**取引余力は CashAvailableForTrading / SpendingPower のみ**。CashBalance は settled cash 表示用で、未決済を含まない (= 過小評価する)。

2026-05-26 セッションで T126816 の取引余力を `CashBalance` から $96 と誤解釈。実際は `SpendingPower` から $649 (差 6.7倍)。詳細: [ADR-026](../../adr/026-external-api-field-discipline.md)

### 7 sub-accounts

`/port/v1/accounts/me` は 7口座 (I161277 / N122798 / P120136 / S153624 / T126816 / TU130134 / X153099) を返す。Excel 取引履歴に登場するのは P120136 / T126816 のみだが、他 5 口座も active (現状残高 0)。

### Position の CurrentPrice = 0

米市場休場中は `PositionView.CurrentPrice` / `MarketValue` が 0 で返る。価格情報は別途 `/trade/v1/prices/` か Parquet (close price) を使う。
