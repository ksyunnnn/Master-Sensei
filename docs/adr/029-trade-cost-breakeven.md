# ADR-029: 取引コストと損益分岐 (break-even) の追跡

Status: accepted
Date: 2026-06-02

## Context

Session 39 でユーザーから「トレードで目指す損益分岐がどこになるのか明確にしたい。スキャルピングのように小さく積み上げるにしても、手数料が利幅を上回れば意味がない」との問題提起があった。

現状を調査した結果:

- `trades.commission_usd` カラムは ADR-015 で定義済みだが **12 trade 中 1 件しか記入されていない**（ADR-015 自身が記入率を「閾値未満・許容」と明記）。
- `pnl_usd` は **グロス**（`(exit−entry)×qty`）で、手数料・為替・スプレッドを一切控除していない。記録上の損益は実損益より過大。
- **取引前にコストを見積もる手段が無い**。サイズ・口座通貨で break-even がどう動くか不明なまま発注していた。

サクソバンク証券は **JPY 口座で USD 建 ETF を売買**する構成のため、為替手数料 (片道0.25%) が往復で効き、これがレバ ETF スキャルの成否を左右する。break-even を可視化しないと「勝率に関係なくコスト負け」する取引を弾けない。

Saxo OpenAPI には取引前コストを返す endpoint が存在する (`/cs/v1/tradingconditions/cost`)。2026-06-02 に実コールし、`TotalCostPct` が往復 break-even% をそのまま返すことを確認した (docs/api/saxo/cost-fields.md)。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A. 現状維持 (gross PnL のみ) | コストゼロ | コスト負け取引を検知不能。スキャル可否を判断できない | 不採用 |
| B. 手数料率を定数でハードコードし自前計算 | API 不要 | 口座ステージ・最低手数料・為替率の変動を追えず乖離。ADR-026「推測禁止」に反する | 不採用 |
| C. **Saxo cost endpoint を権威ソースに、break-even を entry 前に取得 + 実コストで net PnL 記録** | 口座/サイズ/通貨を織り込んだ実数。推測排除 | endpoint 実装・文書化コスト | **採用** |

## Decision

> **取引前に `get_trade_cost()` で往復 break-even% を取得し `/entry-analysis` のシナリオ判断に組み込む。決済時は実 all-in コストを記録し net PnL を残す。**

1. **API アクセサ**: `SaxoClient.get_trade_cost(account_key, uic, asset_type, amount, price, direction)` → `TradeCost` dataclass。`Amount` と `Price` は必須 (Saxo は片方欠けで 400/404)。raw dict は露出しない (ADR-026)。
2. **break-even の主軸**: `TradeCost.total_cost_pct`（`IncludesOpenAndCloseCost` 前提時は往復%）。`break_even_price()` で回収価格を算出。
3. **スキーマ拡張** (`trades`):
   - `breakeven_pct` — entry 時の見積り往復%（後知恵排除のため発注時点で保存）
   - `cost_usd` — 決済時の実 all-in 往復コスト（commission + 為替 + spread + 税）
   - `pnl_net_usd` — `pnl_usd − cost_usd`（実 edge 計測の基準）
   - gross の `pnl_usd` は従来通り併存。
4. **entry-analysis 組み込み**: MAP シナリオごとに break-even を表示し、**target が break-even を上回ること**と**最低手数料に対しサイズが十分か**をサイズ判断 (ADR-028) と並べて確認する。

## Rationale

- `TotalCostPct` は Saxo が口座通貨・ステージ・最低手数料・為替を全て織り込んで返す**実数**であり、自前計算 (案B) の乖離リスクを排除する (ADR-026)。
- 実コール検証で **3株@$227 (円口座) の往復 break-even = 0.869%**、内訳は為替0.501%・手数料0.294%(最低$1.0発動)・スプレッド0.044% と判明。サイズを上げると最低手数料の影響が消え 0.722% に収束、為替0.5%が円口座の下限。→ **米ドル口座運用が break-even を最も下げるレバー**（per-trade 為替が0になる）。これは別途方針判断とする。
- net PnL を残すことで ADR-028 の expectancy 評価が gross の幻想でなく実損益ベースになる。

出典: docs/api/saxo/cost-fields.md（実レスポンス + 公式 citation）

## Consequences

- **反映先**: `src/saxo_client.py`(`TradeCost`/`get_trade_cost`/`SAXO_UIC`)、`src/db.py`(trades 3カラム + `add_trade`/`close_trade`)、`docs/api/saxo/cost-fields.md`(API field)、`docs/api/saxo/fee-schedule.md`(公式手数料体系の普遍的事実)、`.claude/skills/entry-analysis/SKILL.md`、knowledge `K-040`。
- **トレードオフ**: break-even は **取引前の見積り**。実約定コストは決済後に別途記録する (`cost_usd`)。見積りと実績の乖離は net PnL 蓄積で事後検証する。
- **未確定 (将来トリガー)**:
  - symbol→Uic 解決は `SAXO_UIC` の検証済み定数のみ。新規 symbol が増えたら `/ref/v1/instruments` を実装。
  - `cost_usd` の実値取得経路（trade message / balance delta）は未実装。当面は決済時に `get_trade_cost()` の見積りを実コスト近似として記録し、乖離が観測されたら実績取得を実装。
  - 米ドル口座運用への切替判断（break-even を ~0.5% 下げる）は方針として別途。
