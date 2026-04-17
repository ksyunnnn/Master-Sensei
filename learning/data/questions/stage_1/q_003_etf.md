---
id: Q-003
stage: 1
category: basic
term: ETF
type: recall
difficulty: 1
prereqs: [株式, 指数]
---

## Prompt

ETF (Exchange Traded Fund) の定義において **決定的な 2 つの要素** を挙げ、投資信託との違いを 1 点含めて説明してください。

## Rubric

- 取引所上場 (Exchange Traded)
- 指数追跡 or バスケット保有 (Fund)
- 投資信託との違い: ETF は取引時間中いつでも市場価格で売買可、投信は 1 日 1 回基準価額で
- 板 (order book) がある / 短時間で約定

## Explanation

**ETF = Exchange Traded Fund = 取引所上場の投資信託**。定義の核心は 2 語:

1. **Exchange Traded**: 株と同じように**取引所**で**取引時間中いつでも**売買できる。板（order book）が存在し、市場の需給で価格が決まる
2. **Fund**: 内部で**指数** or **バスケット** or **戦略**を追跡する（単一銘柄ではない）

投資信託 (mutual fund) との違い:

| 項目 | ETF | 投資信託 |
|------|-----|---------|
| 売買 | 取引時間中いつでも | 1 日 1 回、基準価額 |
| 価格決定 | 市場の需給 | 基準価額 (NAV) 計算 |
| 板 | あり | なし |
| レバレッジ | あり (SOXL 等) | 限定的 |

SOXL のようなレバレッジ ETF も「取引所上場の投資信託」の枠組みに入る。内部で指数を 3x 追跡するために**スワップ契約・先物**を使っているが、形式は ETF。
