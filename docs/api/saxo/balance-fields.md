# Saxo Balance Response Fields

`/port/v1/balances` および `/port/v1/balances/me` の response object 全 field の公式定義。

**出典 (Primary)**: [Saxo Developer Portal - BalanceResponse schema](https://www.developer.saxo/openapi/referencedocs/port/v1/balances/post__port__subscriptions/schema-balanceresponse)
**出典 (Secondary, user-facing)**:
- [Saxo Support - What is Cash available?](https://www.help.saxo/hc/en-us/articles/360031172191-What-is-Cash-available)
- [Saxo Glossary - Cash balance](https://www.home.saxo/content/glossary/cash-balance)

## Cash 系 fields

### CashBalance

- **型**: Number
- **公式定義** (Saxo schema): "Current cash balance of the account/client."
- **公式定義** (Saxo glossary): "The current value of the cash funds in your account."
- **用途**: settled cash の会計表示
- **本プロジェクトでの推奨**: ❌ **sizing 判断に使わない** (未決済を含まないため過小評価)。`get_settled_cash_balance()` 経由で会計表示用途のみ
- **実例 (2026-05-26 T126816)**: 15,216.61 JPY (実際の取引余力 103,099 JPY とは別物)

### CashAvailableForTrading

- **型**: Number
- **公式定義** (schema): "Cash available for trading for the current account/client."
- **公式定義** (Saxo Support):
  > "Cash available is the funds available for withdrawal or for buying cash products (stocks, bonds, funds, options)."
- **含むもの**: 現金残高 + 未決済取引 + 株式/ETF/債券/ファンド評価額 (ヘアカット後) + オプション時価 + margin 損益
- **含まないもの**: 企業行動 (corporate action) 関連の発生額
- **制約**: "Cash Available can never exceed initial margin available"
- **本プロジェクトでの推奨**: ✅ **sizing 判断に使う**。`get_cash_available_for_trading()` 経由
- **実例 (2026-05-26 T126816)**: 103,099 JPY (settled 15,216 + TransactionsNotBooked 87,882)

### SpendingPower

- **型**: Number
- **公式定義** (schema): "Available spending power on the account/client." (`SpendingPowerDetail` object として返される構造もあり)
- **本プロジェクトでの観測**: `CashAvailableForTrading` と同値 (103,099 JPY)
- **本プロジェクトでの推奨**: ✅ **sizing 判断に使う**。`get_spending_power()` 経由 (CashAvailableForTrading と互換)
- **注意**: 値が CashAvailableForTrading と同じか異なるかは口座種別 (cash account vs margin account) で変わる可能性あり。本プロジェクトの cash account では同値だが、将来 margin 利用時は再検証

### CashBlocked

- **型**: Number
- **公式定義**: "Cash blocked for the current account/client."
- **本プロジェクトでの推奨**: 通常 0。0 でない場合は調査必要

### CashBlockedFromWithdrawal

- **型**: Number
- **公式定義**: ページに記載なし (推測なし、必要時は Saxo Support に確認)
- **本プロジェクトでの観測**: 通常 0

### TransactionsNotBooked

- **型**: Number
- **公式定義**: "Value of transactions that have yet to be booked..."
- **意味**: T+1/T+2 未決済の取引額。CashAvailableForTrading にはこの分も含まれる
- **本プロジェクトでの推奨**: debug/audit 用途。`get_transactions_not_booked()` で参照可
- **実例 (2026-05-26 T126816)**: 87,882 JPY (5/22 SOXL 3株売却 $555 ≒ 88,245 JPY 相当)

### SettlementValue

- **型**: Number
- **公式定義**: "Net current settlement value, long and short..."
- **本プロジェクトでの推奨**: 現在用途なし

## Value 系 fields

### TotalValue

- **型**: Number
- **公式定義**: "Current value of unrealized positions incl. cash balance..."
- **意味**: NAV (cash + 未実現ポジション評価額)
- **本プロジェクトでの推奨**: ✅ NAV 表示・position size 比率算出に使う。`get_total_value()` 経由
- **実例 (2026-05-26 P120136)**: 52,151 JPY (cash 21,901 + SOXL 1株 30,250)

### UnrealizedPositionsValue

- **型**: Number
- **公式定義**: "The current unrealized profit/loss and face value..."
- **本プロジェクトでの推奨**: 含み損益確認。`get_unrealized_pnl()` 経由

### UnrealizedPositionsValueExcludingCostToClosePositions

- **型**: Number
- **公式定義**: ページに記載なし
- **本プロジェクトでの推奨**: 通常用途なし。UnrealizedPositionsValue を使う

### NonMarginPositionsValue

- **型**: Number
- **公式定義**: "Sum of MarketValue for all non-margin instruments held..."
- **意味**: cash instrument (ETF, 株式等) の合計評価額
- **本プロジェクトでの観測 (P120136)**: 30,251.61 JPY (SOXL 1株 $190.56 × FX)

### CostToClosePositions

- **型**: Number
- **公式定義**: ページに記載なし
- **本プロジェクトでの観測**: 負値で記録される (P120136: -176.21)

## Margin 系 fields

### MarginAvailableForTrading

- **型**: Number
- **公式定義**: "Margin available for trading..."
- **本プロジェクトでの推奨**: cash account では通常使わない。CFD/FX 利用時に重要

### NetEquityForMargin

- **型**: Number
- **公式定義**: "Value used as basis to calculate maintinance margin."
- **本プロジェクトでの推奨**: margin 計算 base 値 (現状用途なし)

### CollateralAvailable

- **型**: Number
- **公式定義**: "Sum of collateral from positions, cash, collateral..."
- **本プロジェクトでの推奨**: 現状用途なし

### CollateralCreditValue

- **型**: dict (構造)
- **本プロジェクトでの推奨**: 現状用途なし

### InitialMargin

- **型**: Number
- **公式定義**: ページに記載なし
- **本プロジェクトでの推奨**: cash account では 0

### MarginCollateralNotAvailable

- **型**: 構造 (詳細: `MarginCollateralNotAvailableDetail`)
- **本プロジェクトでの推奨**: 現状用途なし

### MarginAndCollateralUtilizationPct

- **型**: Number
- **公式定義**: ページに記載なし
- **本プロジェクトでの推奨**: 現状用途なし

## Position count 系 fields

### OpenPositionsCount

- **型**: Integer
- **公式定義**: "Number of current open positions."
- **本プロジェクトでの推奨**: ✅ open position 数の確認

### ClosedPositionsCount

- **型**: Integer
- **公式定義**: "Number of current closed positions."
- **意味**: 同日中にクローズした position 数 (settling 中含む可能性)
- **本プロジェクトでの観測 (T126816)**: 1 (5/22 SOXL 3株 entry → 同日 exit)

### NetPositionsCount

- **型**: Integer
- **公式定義**: "Number of current open net positions."
- **本プロジェクトでの観測**: open + 未決済 closed の合計と推測 (公式定義あいまい)

### OpenIpoOrdersCount / OrdersCount / TriggerOrdersCount

- **型**: Integer
- **本プロジェクトでの推奨**: 現状用途なし

## 損益系 fields

### UnrealizedMarginProfitLoss / UnrealizedMarginOpenProfitLoss / UnrealizedMarginClosedProfitLoss

- **型**: Number
- **公式定義**: ページに記載なし
- **本プロジェクトでの観測**: cash account では全て 0

### OptionPremiumsMarketValue

- **型**: Number
- **本プロジェクトでの推奨**: option 取引なし、常に 0

## メタ系 fields

### Currency

- **型**: VARCHAR
- **意味**: 口座通貨 (JPY / USD 等)
- **本プロジェクトでの観測**: 5 口座 JPY、2 口座 USD

### CurrencyDecimals

- **型**: Integer
- **意味**: 通貨の小数点桁数 (JPY: 0, USD: 2 等)

### CalculationReliability

- **型**: VARCHAR
- **公式定義**: ページに記載なし
- **本プロジェクトでの観測**: "Ok" (正常時)
- **本プロジェクトでの推奨**: "Ok" 以外の値は調査必要

### IsPortfolioMarginModelSimple

- **型**: Boolean
- **本プロジェクトでの観測**: True (cash account)

### CorporateActionUnrealizedAmounts

- **型**: Number
- **本プロジェクトでの観測**: 0 (現状コーポレートアクションなし)

### FinancingAccruals

- **型**: Number
- **本プロジェクトでの観測**: 0 (margin/CFD 未利用)

### ChangesScheduled

- **型**: Boolean
- **公式定義**: ページに記載なし

### ExtendedTradingHoursData / ExtendedTradingHoursUncertaintyValue

- **型**: 構造 / Number
- **本プロジェクトでの推奨**: 時間外取引利用時のみ

### SrdSpendingPower

- **型**: Number (推測)
- **公式定義**: ページに記載なし (推測せず、必要時は Saxo Support 確認)
- **本プロジェクトでの観測 (T126816)**: 103,099 (SpendingPower と同値)

### SpendingPowerDetail

- **型**: dict
- **公式定義** (schema): "Available spending power on the account/client." (構造化版)
- **本プロジェクトでの推奨**: 詳細不要時は flat な `SpendingPower` を使う

### TransactionsNotBookedDetail

- **型**: dict
- **本プロジェクトでの観測 (T126816)**: 4 key の構造 (T+2 settling の trade 内訳)

### MarginCollateralNotAvailableDetail

- **型**: dict (2 key)
- **本プロジェクトでの推奨**: 現状用途なし

### OtherCollateral

- **型**: Number
- **本プロジェクトでの観測**: 0

## 改訂履歴

- 2026-05-26: 初版作成。Saxo Live API 実レスポンス (P120136 / T126816) を基に全 field を網羅。公式 schema から取得できなかった field は「ページに記載なし」と明示。
