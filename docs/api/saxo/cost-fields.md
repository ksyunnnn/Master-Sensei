# Saxo Trade Cost Response Fields

`GET /cs/v1/tradingconditions/cost/{AccountKey}/{Uic}/{AssetType}` の response object 全 field の公式定義。**取引前のコスト見積り = break-even 判定**に使う (ADR-029)。

**出典 (Primary)**: [Saxo Developer Portal - TradingCost schema](https://developer.saxobank.com/openapi/referencedocs/cs/v1/tradingconditions-cost/get__cs_tradingconditions_cost_accountkey_uic_assettype/schema-tradingcost)
**出典 (Secondary)**:
- [How do I find the costs associated with an instrument? (Saxo OpenAPI Support)](https://openapi.help.saxo/hc/en-us/articles/4417467757713-How-do-I-find-the-costs-associated-with-an-instrument)
- [米国株の取引手数料と為替手数料とは？ (サクソバンク証券)](https://www.home.saxo/ja-jp/learn/guides/equities/understanding-us-stock-and-currency-exchange-fees-costs)

> 本ドキュメントは **API レスポンスの読み方**。手数料率そのものの普遍的事実 (commission ステージ別料率・為替・カストディ等) は [fee-schedule.md](fee-schedule.md) を参照。

## リクエスト

```
GET /cs/v1/tradingconditions/cost/{AccountKey}/{Uic}/{AssetType}?Amount={amount}&Price={price}
```

- **`AccountKey`**: 口座キー (口座通貨でコストが変わる。円口座は為替コストが乗る)
- **`Uic`**: instrument の一意 ID (SOXL = 46780)
- **`AssetType`**: `Etf` / `Stock` 等
- **`Amount`**: 数量。**必須** (欠けると 400)
- **`Price`**: 価格。**必須** (欠けると 400)。両方揃って初めて 200

> ⚠️ `Amount` か `Price` のどちらかが欠けると Saxo は `400 Bad Request`、両方欠けると `404` を返す。意味的アクセサ `SaxoClient.get_trade_cost()` は両方を必須引数にしている。

## レスポンス構造

```
{
  "AccountCurrency": "JPY",         // 口座通貨
  "Amount": 3.0, "Price": 227.0, "Uic": 46780, "AssetType": "Etf",
  "Instrument": "Direxion Daily Semiconductor Bull 3X ETF",
  "HoldingPeriodInDays": 0,
  "CostCalculationAssumptions": ["IncludesOpenAndCloseCost", ...],
  "Cost": {
    "Long":  { ...片側 (Buy で建て Sell で閉じる) のコスト... },
    "Short": { ...必要時のみ... }
  }
}
```

`Cost.Long` / `Cost.Short` の中身が実コスト。本プロジェクトは SOXL 順張りロング中心 (ADR-028) のため通常 `Long` を読む。

## トップレベル field

### AccountCurrency

- **公式定義**: 口座の基準通貨。
- **意味**: USD 建 instrument を **JPY 口座**で取引すると `ConversionCost` (為替手数料) が発生する。`instrument_currency` (= `Cost.Long.Currency`) と異なる場合に為替コストが乗る。

### CostCalculationAssumptions

- **公式定義**: コスト算出の前提リスト。
- **重要値**:
  - **`IncludesOpenAndCloseCost`**: コストが **open + close の往復**を含む。これが含まれるとき `TotalCostPct` は **往復 break-even 値幅%** になる。
  - `EquivalentOpenAndClosePrice`: open と close の価格を同一と仮定。
  - `ImplicitCostsNotChargedOnAccount`: spread 等の implicit cost は口座に直接課金されない (価格に内包)。
- **本プロジェクトでの推奨**: `get_trade_cost()` は `IncludesOpenAndCloseCost` の有無を `is_round_trip` として返す。break-even を語る前に必ずこれを確認する。

## `Cost.Long` / `Cost.Short` 配下の field

### Cost.Currency {#cost-currency}

- **公式定義**: コスト額の通貨 (= instrument 通貨)。
- **実例**: SOXL = `USD`。`AccountCurrency` (JPY) と異なるため為替コストが発生。

### TotalCost {#totalcost}

- **公式定義**: 全コスト合算の絶対額 (Cost.Currency 建)。
- **実例 (2026-06-02 SOXL 3株@$227 / 円口座)**: `5.92` USD。

### TotalCostPct {#totalcostpct}

- **公式定義**: TotalCost ÷ notional の百分率。
- **意味**: `is_round_trip=True` のとき **往復 break-even 値幅%**。long ならエントリーをこの % 上回れば損益分岐。
- **本プロジェクトでの推奨**: ✅ これが break-even の主軸。`get_trade_cost().total_cost_pct` / `.break_even_price()`。
- **実例**: 3株@$227 → `0.869%` (= $228.97 で分岐)。サイズが上がると最低手数料の影響が薄れ低下 (10株〜 → 0.722%)。

### TradingCost.Commissions {#commissions}

- **公式定義**: 売買手数料の配列。`Value` (絶対額)、`Pct` (対 notional %)、`Rule.MinCommission` (最低手数料)、`Rule.Currency`。
- **意味**: notional × 料率。ただし `MinCommission` を下回る場合は最低額が適用され、**小サイズほど実効 `Pct` が上昇**する。
- **実例 (サクソバンク証券 Classic)**: 料率 0.088%、**`MinCommission` = 1.0 USD**。3株=$681 では 0.088%=$0.60 < $1.0 のため最低額が発動 (往復 `Value`=2.0、`Pct`=0.294%)。約定代金 ~$1,250 超で最低額が外れ実効 0.088% に収束。
- **注意**: `Commissions` は配列。複数手数料がある instrument では先頭以外も合算が要る場合あり (現状 SOXL は単一)。

### TradingCost.ConversionCost {#conversioncost}

- **公式定義**: 通貨換算 (為替) コスト。`Value` (絶対額)、`Pct` (往復対 notional %)、`Rule.Pct` (片道換算率)。
- **意味**: **JPY 口座で USD 建 instrument を売買する都度**発生。買いで JPY→USD、売りで USD→JPY の2回。
- **実例**: `Rule.Pct` = 0.25 (片道0.25%)、往復 `Pct` = 0.501%、`Value` = $3.41。**円口座の break-even を支配する最大要因**。
- **重要**: **米ドル口座で保有すれば per-trade の換算コストは 0**(円→ドル資金移動時に一度だけ0.25%)。break-even を最も下げるレバー (ADR-029)。

### TradingCost.Spread {#spread}

- **公式定義**: bid/ask スプレッドの implicit cost。`Value` (絶対額)、`Pct`。
- **実例**: `Pct` = 0.044%、`Value` = $0.3。`ImplicitCostsNotChargedOnAccount` のため口座に直接課金はされないが実質コスト。

### HoldingCost {#holdingcost}

- **公式定義**: 保有に伴うコスト (税・取引所手数料等)。`Tax` 配列に各項目の `Value`/`Pct`/`Rule`。
- **実例**: `CTaxOnCommission` ($0.2、手数料への10%課税) + `SEC手数料` ($0.01、売り側)。短期保有では小さい。
- **本プロジェクトでの推奨**: `get_trade_cost().holding_cost` は `Tax` 配列の `Value` 合算。financing/金利は cash 口座のため通常 0。

## 意味的アクセサ (src/saxo_client.py)

| アクセサ | 返すもの | 用途 |
|---------|---------|------|
| `get_trade_cost(account_key, uic, asset_type, amount, price, direction)` | `TradeCost` dataclass | 取引前コスト見積り (推奨インタフェース) |
| `TradeCost.total_cost_pct` | `TotalCostPct` | 往復 break-even% (主軸) |
| `TradeCost.break_even_price()` | 算出値 | コスト回収価格 (long=上, short=下) |
| `TradeCost.conversion_cost_pct` / `.conversion_rate_pct` | `ConversionCost.Pct` / `.Rule.Pct` | 為替コスト (円口座の主因) |
| `TradeCost.commission` / `.min_commission` | `Commissions[0].Value` / `.Rule.MinCommission` | 最低手数料の発動検知 |
| `TradeCost.is_round_trip` | `IncludesOpenAndCloseCost` の有無 | break-even の往復/片道判定 |

`SAXO_UIC` (src/saxo_client.py) に取引ユニバースの検証済み `(Uic, AssetType)` を保持。新規 symbol は `/ref/v1/instruments` で解決 (未実装、必要時に追加)。

## 検証履歴

| 日付 | 内容 |
|------|------|
| 2026-06-02 | SOXL (Uic 46780, Etf) を live 口座 T126816 で実コール。本ドキュメントの全 field・実例はこのレスポンスに基づく |
