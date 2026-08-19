# Closed Position Fields — GET /port/v1/closedpositions/me

クローズ済ポジション (決済済 open→close ペア) の field 定義 (ADR-026)。
`SaxoClient.get_closed_positions()` が `ClosedPosition` dataclass に意味的展開する。

- citation: Saxo OpenAPI Reference — Portfolio / ClosedPositions (`GET /port/v1/closedpositions/me`)
- **即時性**: 決済当日に返る。`/cs/v1/reports/trades/` (booking, T+1) を待たない
- **用途**: `/sync-saxo` の「台帳に余分」break を **booking 待ちか真の乖離か**に切り分ける
  (`SenseiDB.explain_ledger_surplus_by_closed_positions`)

## なぜこの層が要るか

執行事実層 `account_transactions` の供給源は `reports/trades` で、**booking は T+1**。
決済当日は台帳に sell 行が入らないため、3層照合は「ライブ建玉=0 / 台帳net>0」を
**真の乖離と誤報**する。本 endpoint は同じ Saxo 由来でありながら決済当日に読めるので、
その差分を「booking 待ち (benign)」と説明できる。

🔬 2026-08-19 の SOXL 24株決済で実証。ライブ建玉=0 / 台帳net=24 の break に対し、
本 endpoint は決済2件 (12株×2, ClosingPrice $120.03) を即時返した。

## Query parameter

`?FieldGroups=ClosedPosition,DisplayAndFormat` を付ける。
`ClosedPosition` を要求しないと数量・価格・損益がすべて欠落する
(positions の `PositionBase` と同じ構造)。

## 主要 field (`Data[]` の各要素)

| path | 型 | 意味 | ClosedPosition |
|------|----|----|----|
| `ClosedPositionUniqueId` | str | `{OpeningPositionId}-{ClosingPositionId}` 連結。一意キー | `unique_id` |
| `ClosedPosition.AccountId` | str | どの口座か | `account_id` |
| `ClosedPosition.Uic` | int | instrument 一意 ID | `uic` |
| `ClosedPosition.Amount` | float | 決済数量 (**常に正**) | `amount` |
| `ClosedPosition.BuyOrSell` | str | **ポジションを開いた方向**。下記の罠を参照 | `opening_side` |
| `ClosedPosition.OpenPrice` | float | 建値 (instrument 通貨) | `open_price` |
| `ClosedPosition.ClosingPrice` | float | **決済価格** (instrument 通貨) | `closing_price` |
| `ClosedPosition.ExecutionTimeOpen` | str | 建玉約定時刻 (UTC ISO8601、原文保持) | `execution_time_open_utc` |
| `ClosedPosition.ExecutionTimeClose` | str | **決済約定時刻** (UTC ISO8601、原文保持) | `execution_time_close_utc` |
| `ClosedPosition.OpeningPositionId` | str | 建玉側 PositionId。**OrderId ではない** | `opening_position_id` |
| `ClosedPosition.ClosingPositionId` | str | 決済側 PositionId。**OrderId ではない** | `closing_position_id` |
| `ClosedPosition.ProfitLossOnTrade` | float | 価格変動のみの損益 (instrument 通貨) | `pnl_instrument` |
| `ClosedPosition.ProfitLossOnTradeInBaseCurrency` | float | 同上を口座通貨換算 | `pnl_base` |
| `ClosedPosition.ProfitLossCurrencyConversion` | float | **FX 変換損益** (口座通貨)。下記参照 | `pnl_fx_conversion_base` |
| `ClosedPosition.ClosedProfitLoss` | float | 実現損益 (instrument 通貨、**手数料除く**) | `closed_pnl_instrument` |
| `ClosedPosition.ClosedProfitLossInBaseCurrency` | float | 実現損益 (口座通貨、**手数料除く**) | `closed_pnl_base` |
| `ClosedPosition.CostOpening` | float | 建玉時コスト (instrument 通貨、**負値**) | `cost_opening_instrument` |
| `ClosedPosition.CostClosing` | float | 決済時コスト (instrument 通貨、**負値**) | `cost_closing_instrument` |
| `ClosedPosition.CostOpeningInBaseCurrency` | float | 同上を口座通貨換算 (負値) | `cost_opening_base` |
| `ClosedPosition.CostClosingInBaseCurrency` | float | 同上を口座通貨換算 (負値) | `cost_closing_base` |
| `ClosedPosition.ClosingMethod` | str | `Fifo` 等の建玉充当方式 | `closing_method` |
| `ClosedPosition.AssetType` | str | `Etf` 等 | `asset_type` |
| `DisplayAndFormat.Symbol` | str/null | `SOXL:arcx` 形式。`:` 前を正規化 | `symbol` |
| `DisplayAndFormat.Currency` | str | instrument 通貨 (例 `USD`) | `instrument_currency` |

symbol 正規化は position-fields.md と共通 (`_normalize_symbol`)。

## 罠1: `BuyOrSell` は決済の方向ではない

**`BuyOrSell` は建玉を開いた方向**を指す。long を買って売り決済しても `"Buy"` のまま。
「決済で売ったのだから `Sell` だろう」と変数名から推測すると符号を取り違える (ADR-026)。

🔬 2026-08-19 実測: SOXL を $134.13 で買い、$120.03 で売却決済 → `BuyOrSell="Buy"`。

台帳の sell 行を導出する用途では、**`opening_side="Buy"` の決済は sell 行**、
`"Sell"` の決済は buy 行に対応する (符号を反転させる)。

## 罠2: OrderId が返らない

本 endpoint は **`OrderId` を一切返さない**。返るのは `OpeningPositionId` /
`ClosingPositionId` (PositionId) のみで、これらは `trades.broker_ref` (=OrderId) と
**別物**である (trade-report-fields.md の規約と同じ)。

したがって `trades` 行と **1対1で機械結合できない**。本層の照合は
「instrument 単位の数量合計が台帳の余剰を説明するか」に留め、
個々の `trades` 行への価格書き戻しは人間が確認して行う。

## 損益の内訳 (実測で検証した恒等式)

🔬 2026-08-19 SOXL 12株 × 2件で検算し、口座残高の実減少と ¥2 (丸め) まで一致。

```
ClosedProfitLossInBaseCurrency
    = ProfitLossOnTradeInBaseCurrency + ProfitLossCurrencyConversion
```

**`ClosedProfitLoss` は手数料 (`CostOpening`/`CostClosing`) を含まない。**
口座通貨での all-in 実現損益は次で求める:

```
all_in_base = ClosedProfitLossInBaseCurrency
            + CostOpeningInBaseCurrency + CostClosingInBaseCurrency
```

(`Cost*` は負値なので加算する。)

観測値 (1件あたり):

| field | 値 |
|-------|----|
| `ProfitLossOnTrade` | -169.20 USD |
| `ProfitLossOnTradeInBaseCurrency` | -27,082.60 JPY |
| `ProfitLossCurrencyConversion` | -2,943.66 JPY |
| `ClosedProfitLossInBaseCurrency` | -30,026.26 JPY |
| `CostOpeningInBaseCurrency` | -227 JPY |
| `CostClosingInBaseCurrency` | -206 JPY |

2件合計の all-in = **-60,918.52 JPY**。口座は ¥594,744 → ¥533,827.53 (**-¥60,916.47**)。

### `ProfitLossCurrencyConversion` は独立したコスト源

円口座で USD 建 ETF を売買すると、価格変動損益とは**別に** FX 変換損益が発生する。
上記の実測では超過損の 84% がこの項だった。cost-fields.md の
`conversion_cost` (事前見積り) に対する**事後の実績値**がこの field である。

## 保持期間 — 全履歴は返らない

🔬 2026-08-20 06:22 JST 実測: `__count=2` で **8/19 決済分のみ**が返った。同口座には
それ以前にも決済済み往復 (例: 2026-08-03 の SOXL 往復) が存在し台帳に記録されているが、
本 endpoint には**現れなかった**。

したがって closedpositions は**直近の未決済 (unsettled) 分のみ**を返す層として扱う。
全履歴の SoT はあくまで `reports/trades` = `account_transactions` であり、
本 endpoint を過去分の照合や成績集計に使わない。
