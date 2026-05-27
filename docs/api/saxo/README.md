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
| [endpoints.md](endpoints.md) | 使用 4 endpoint + 実例レスポンス |
| [rate-limits.md](rate-limits.md) | rate limit 公式値 |

## 用途別 field 早見表

**重要**: 解釈前に必ず balance-fields.md を参照 (ADR-026)。

| 用途 | 使う field | 使ってはいけない field | 理由 |
|------|----------|--------------------|------|
| **新規取引の sizing (今夜 SOXL 何株買えるか)** | `CashAvailableForTrading` または `SpendingPower` | `CashBalance` | CashBalance は settled cash のみ。未決済分 (TransactionsNotBooked) を含まないため過小評価する |
| 口座評価額 (NAV) | `TotalValue` | `CashBalance` | TotalValue = cash + 未実現ポジション評価額 |
| 含み損益確認 | `UnrealizedPositionsValue` | - | |
| margin 必要量算出 | `NetEquityForMargin` | `TotalValue` | NetEquityForMargin が margin 計算の正式 base |
| margin 余力確認 | `MarginAvailableForTrading` | `CashAvailableForTrading` | margin instrument (CFD/FX) では別の field |

## 意味的アクセサ (src/saxo_client.py)

| アクセサ | 返す field | 用途 |
|---------|----------|------|
| `get_spending_power(account_key)` | `SpendingPower` | sizing 判断 (これを使う) |
| `get_cash_available_for_trading(account_key)` | `CashAvailableForTrading` | sizing 判断 (SpendingPower と同じ値、互換性のため) |
| `get_settled_cash_balance(account_key)` | `CashBalance` | 会計表示用 (sizing には使わない) |
| `get_total_value(account_key)` | `TotalValue` | NAV |
| `get_unrealized_pnl(account_key)` | `UnrealizedPositionsValue` | 含み損益 |
| `get_transactions_not_booked(account_key)` | `TransactionsNotBooked` | T+2 未決済額 (debug 用) |
| `get_balances()` (raw) | 全 field | 調査用途のみ |

## 既知の落とし穴

### CashBalance vs CashAvailableForTrading vs SpendingPower

3つとも英語名が似ているが意味が違う。**取引余力は CashAvailableForTrading / SpendingPower のみ**。CashBalance は settled cash 表示用で、未決済を含まない (= 過小評価する)。

2026-05-26 セッションで T126816 の取引余力を `CashBalance` から $96 と誤解釈。実際は `SpendingPower` から $649 (差 6.7倍)。詳細: [ADR-026](../../adr/026-external-api-field-discipline.md)

### 7 sub-accounts

`/port/v1/accounts/me` は 7口座 (I161277 / N122798 / P120136 / S153624 / T126816 / TU130134 / X153099) を返す。Excel 取引履歴に登場するのは P120136 / T126816 のみだが、他 5 口座も active (現状残高 0)。

### Position の CurrentPrice = 0

米市場休場中は `PositionView.CurrentPrice` / `MarketValue` が 0 で返る。価格情報は別途 `/trade/v1/prices/` か Parquet (close price) を使う。
