# Saxo 手数料体系 (サクソバンク証券・米国株/ETF)

サクソバンク証券で**米国株/ETF を取引する際の公式手数料体系**の普遍的事実をまとめる。
個別トレードの実測値ではなく「制度として常に成り立つ事実」の一次資料。

**出典 (Primary, 公式)**:
- [米国株の取引手数料と為替手数料とは？ (サクソバンク証券)](https://www.home.saxo/ja-jp/learn/guides/equities/understanding-us-stock-and-currency-exchange-fees-costs)
- [外国株式取引手数料 (サクソバンク証券)](https://www.home.saxo/rates-and-conditions/stocks/commissions)
- [外国株式・外国ETF/ETN取引概要 (サクソバンク証券)](https://www.home.saxo/rates-and-conditions/stocks/trading-conditions)

**出典 (Primary, API)**:
- `/cs/v1/tradingconditions/cost/{AccountKey}/{Uic}/{AssetType}` — 取引コスト見積り
- `/cs/v1/tradingconditions/instrument/{AccountKey}/{Uic}/{AssetType}` — 口座固有の条件 (`CommissionLimits` / `CustodyFees` / `CurrencyConversion` / `CurrentSpread` / `VatOnCustodyFeePct`)

**確度の凡例**:
- ✅ **公式** = サクソバンク証券公式ページに記載
- 🔬 **API実測** = 上記 endpoint の実レスポンスで確認 (2026-06-02, 口座 T126816)
- ⚠️ **未確認** = 一次資料で数値を確認できておらず要追確認

## 1. 取引手数料 (commission)

| アカウントステージ | 公式表記 料率 (約定代金×) | 確度 |
|---|---|:--:|
| Classic | 0.088% | ✅ 公式 |
| Platinum | 0.055% | ✅ 公式 |
| VIP | 0.033% | ✅ 公式 |

- **当口座 (T126816) の実適用料率 = 0.08% / 片道**。🔬 API実測 (`CommissionLimits[].RateOnAmount = 0.0008`)。公式 Classic 表記 0.088% とわずかに差があり、**実際に課金される率は 0.08%**。
- **最低手数料 = 1.0 USD / 片道**。🔬 API実測 (cost endpoint `Commissions[].Rule.MinCommission` と instrument endpoint `CommissionLimits[].MinCommission` の**2経路で一致**)。
  - 二次情報 (diamond.jp 等) の「$1.10」は不採用 (API 現契約値 $1.0 を正とする)。
  - 約定代金が **~$1,250 未満**だと料率分が $1.0 を下回り最低手数料が支配し、実効料率が上昇する。
- 例 (Classic 公式): $4,000 の取引 → $3.52。

## 2. 為替手数料 (currency conversion)

| 決済口座 | per-trade 換算コスト | 確度 |
|---|---|:--:|
| **円口座 (JPY)** | **片道 0.25% / 往復 0.5%** (買=円→ドル, 売=ドル→円の2回) | ✅ 公式 + 🔬 API実測 |
| **米ドル口座 (USD)** | **無料** (円→ドルの資金移動時に一度だけ 0.25%) | ✅ 公式 |

- 🔬 API実測: `ConversionCost.Rule.Pct = 0.25` (片道)、円口座での往復が break-even の最大要因。
- **含意**: 米ドル口座で保有すれば per-trade 為替が消え、往復 break-even を最大 ~0.5% 下げられる。

## 3. 保有・その他コスト

| 項目 | 内容 | 確度 |
|---|---|:--:|
| カストディ費用 | **SOXL / 当口座(T126816)では現在 課金なし** (`CustodyFees.FeeRules` が空)。公式上は株/ETF/債券保有に年間費用・日次計算/月次請求が適用されうる。課金時は VAT 10% (`VatOnCustodyFeePct`) | 🔬 API実測 (現状なし) + ✅ 公式 (制度として存在) |
| SEC手数料 | 売り側に少額課金 | 🔬 API実測 (`HoldingCost.Tax`) |
| 手数料への課税 (C-Tax) | commission に対し 10% | 🔬 API実測 (`CTaxOnCommission`) |
| スプレッド | bid/ask の implicit cost (口座に直接課金されない) | 🔬 API実測 (`Spread`) |
| financing / 金利 | cash 口座のため無し (margin 利用時のみ) | 確信度85% |

> カストディ料率そのもの (公式の年率) は公開ページに無く、プラットフォームの取引条件画面 (instrument → ⓘ → Trading rates) でのみ確認可。ただし **API 上は当口座の SOXL に現在 custody が適用されていない**ため、短期保有では実害なし。長期保有や他銘柄では `tradingconditions/instrument` の `CustodyFees.FeeRules` を都度確認する。

## 4. 往復 break-even の構造

往復コスト (= break-even 値幅%) の内訳:

```
往復コスト% ≈ 為替(円口座 0.5% / 米ドル口座 0%)
            + 手数料(0.088%×2、ただし最低 $1.0/片道)
            + spread(~0.04%)
            + 税(commission への 10% 等、小)
```

- **円口座の下限は為替の 0.5%**。サイズを上げても為替は消えない。
- **小サイズは最低手数料 $1.0 で break-even が上昇**する。
- 正確な値は口座・サイズ・銘柄で変わるため、発注前に `SaxoClient.get_trade_cost()` で取得する (ADR-029, [cost-fields.md](cost-fields.md))。

## 付録: 実測スナップショット (履歴)

| 日付 | 銘柄/サイズ/口座 | 往復 break-even | 内訳 |
|---|---|---|---|
| 2026-06-02 | SOXL 3株 @$227 / T126816(円) | **0.869%** | 為替0.501% + 手数料0.294%(min$1発動) + spread0.044% + 税 |
| 2026-06-02 | SOXL 10–50株 @$227 / T126816(円) | **0.722%** | 最低手数料が外れ実効手数料0.16%、為替0.5%は不変 |

実測値は契約ステージ・為替レート・Saxo 仕様変更で動くため、判断時は最新を `get_trade_cost()` で再取得すること。
