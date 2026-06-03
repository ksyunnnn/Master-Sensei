# Saxo Historical Report Data — Bookings (`/cs/v1/reports/bookings/{ClientKey}`)

入出金・現金移動の供給源（ADR-030 Phase 5）。`account_transactions`（Parquet）の
`deposit`/`withdrawal` 行はここから写像する。

- 公式: https://www.developer.saxo/openapi/referencedocs/cs/v1/historicalreportdata-bookings
- 検証: **2026-06-03 live で HTTP 200 確認**（ClientKey `GEsNp3...`、`FromDate=2026-01-01`〜`ToDate=2026-06-03` で 108 行）。事実検証3段階（存在・動作・契約状態）クリア。
- code: `SaxoClient.get_bookings()` → `CashBooking` のリスト（raw dict 露出禁止、ADR-026）
- 写像: `src/account_ledger.py` `cash_bookings_to_rows()`

## リクエスト

```
GET /cs/v1/reports/bookings/{ClientKey}?FromDate=YYYY-MM-DD&ToDate=YYYY-MM-DD
```

- path: `ClientKey`（必須）
- query: `FromDate`/`ToDate`（任意。または `FilterType`+`FilterValue`）, `AccountKey`, `AccountGroupKey`, `$top`/`$skip`/`$skiptoken`

## レスポンス（`Data[]` の 1 行 = 1 記帳エントリ）

`bookings` は**記帳＝全勘定エントリー**（約定の内訳＋現金移動＋手数料内訳）を返す。
trades report より粒度が細かい。本プロジェクトは **`AssetType='Cash'` の行のみ**を
現金移動として取り込む（ETF 行は約定の内訳で、`reports/trades` と二重計上になるため取らない）。

### 取り込む field（`AssetType='Cash'` 行）

| field | 意味 | account_transactions への写像 |
|------|------|------|
| `AssetType` | `'Cash'`=現金移動、`'Etf'`等=約定内訳 | フィルタ条件（Cash のみ取込） |
| `BkAmountId` | 記帳エントリの一意 ID | `broker_ref`（現金行の主キー。TradeId は無い） |
| `AccountId` | 口座（例 `77800/T126816`） | `account_id` |
| `Date` | 記帳日 | `trade_date` |
| `ValueDate` | 受渡日 | `settlement_date` |
| `AmountUSD` | **USD 換算額。符号付（+ = cash in）** | `amount`（currency=`USD`） |
| `AmountAccountCurrency` | 口座通貨での額 | `amount_jpy` |
| `AccountCurrency` | 口座通貨（例 `JPY`） | （fx_rate 算出に使用） |
| `InstrumentSymbol` | 現金種別コード（例 `CASHINTRTP`=口座間振替） | `instrument`（性質を保持して可逆に） |
| `InstrumentDescription` | 説明（例 "Interaccount transfer..."） | （参考。列は持たない） |

### type の決定（ADR-030 Phase 5）

- `AmountUSD >= 0` → `'deposit'`、`AmountUSD < 0` → `'withdrawal'`
- symbol 値にハードコードしない（外部 deposit/withdrawal の symbol は未観測のため、向きは符号で判定）
- 口座間振替（`CASHINTRTP`）の「入」も、この取引口座にとっては資金供給なので機能的に `deposit`。元の性質は `instrument` 列の symbol で可逆。

### 観測値（2026-06-03 live、`AssetType='Cash'` 4 件）

```
Date        Symbol      AmountUSD   AmountAccountCurrency  Description
2026-03-11  CASHINTRTP    +314.53          +50,000 JPY    Interaccount transfer within different client
2026-03-31  CASHINTRTP    +945.38         +150,000 JPY    （同上）
2026-05-21  CASHINTRTP    +314.49          +50,000 JPY    （同上）
2026-05-29  CASHINTRTP   +1255.67         +200,000 JPY    （同上）
```

## 既知の未確認（事実検証の留保）

- 本口座の Cash 行はすべて**口座間振替**で、**外部銀行からの deposit/withdrawal は履歴に存在しない**。そのため外部入出金の `InstrumentSymbol`/符号の表現は**未確認**（確信度: 振替捕捉=95% / 外部も同型=70%）。
- `AmountClass='TransactionCosts'`（手数料内訳: Commission / 各種税 / Exchange Fee）も bookings に含まれるが、本プロジェクトはコストを `reports/trades` 側で扱うため取り込まない（将来コスト精度向上の余地）。
