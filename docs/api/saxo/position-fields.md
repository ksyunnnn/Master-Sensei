# Position Fields — GET /port/v1/positions/me

ライブ open positions の field 定義 (ADR-026)。`SaxoClient.get_live_positions()` が
`LivePosition` dataclass に意味的展開する。**`/sync-saxo` の live↔台帳照合**
(`SenseiDB.reconcile_live_positions`) で mirror 漏れ検出に使う。

- citation: Saxo OpenAPI Reference — Portfolio / Positions (`GET /port/v1/positions/me`)
- 結合: `Uic` または正規化 `Symbol` で執行事実層 `account_transactions.instrument` と突合
- **注意**: 価格 (`OpenPrice`/`Amount`) は照合に使わない。照合は **net 数量のみ**
  (買売 fill の純和 vs ライブ建玉数量)。価格突合は別途。

## Query parameter

symbol を得るには `?FieldGroups=DisplayAndFormat,PositionView` が必須
(無しだと `DisplayAndFormat.Symbol = null`、endpoints.md の実例参照)。

## 主要 field (`Data[]` の各要素)

| path | 型 | 意味 | LivePosition |
|------|----|----|----|
| `PositionBase.AccountId` | str | どの口座か (e.g. `77800/P120136`) | `account_id` |
| `PositionBase.Uic` | int | instrument 一意 ID (SOXL=46780) | `uic` |
| `PositionBase.Amount` | float | 数量 (正=long, 負=short) | `amount` |
| `PositionBase.OpenPrice` | float | entry price | `open_price` |
| `PositionView.ProfitLossOnTradeInBaseCurrency` | float | 含み損益 (base=JPY) | `unrealized_pnl_base` |
| `DisplayAndFormat.Symbol` | str/null | `SOXL:arcx` 形式。`:` 前を正規化 | `symbol` |

## symbol 正規化

`_normalize_symbol(raw, uic)`:
1. `DisplayAndFormat.Symbol` があれば `:` 前 (`SOXL:arcx` → `SOXL`)
2. なければ `SAXO_UIC` 逆引き
3. それも無ければ `UIC:<n>` (照合で未知 instrument として可視化)

## 検証状態

- `PositionBase.{AccountId,Uic,Amount,OpenPrice}` / `PositionView.ProfitLossOnTradeInBaseCurrency`:
  2026-05-26 live (P120136 SOXL 1株) で確認済 (endpoints.md 実例)。
- `DisplayAndFormat.Symbol` (FieldGroups 付き) の実値は次回 live 建玉保有時に検証する。
  accessor は required field 欠落時に `SaxoAuthError` を投げる (静かな誤照合を防ぐ)。
