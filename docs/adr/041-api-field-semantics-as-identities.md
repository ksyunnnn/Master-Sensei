# ADR-041: 外部 API field の意味は恒等式として実測に固定する

Status: accepted
Date: 2026-09-01

Extends: ADR-026 (外部 API 統合における field 規律)

> ADR-026 を supersede しない。ADR-026 の要求（`docs/api/<provider>/` への公式仕様
> citation、raw dict access 禁止、意味的アクセサ経由）はすべて維持したまま、
> **検証要件を1つ追加する**。

## Context

ADR-026 は「API field の意味を変数名から推測しない。公式仕様を
`docs/api/<provider>/` に citation する」ことを要求している。しかし
**citation した解釈が実データと合っているかの検証は要求していない**。
結果、公式定義を正しく引用したうえで、その解釈を誤って書くことができ、
かつその誤りは静かに残り続ける。

2026-09-01 に実測した具体例（K-081）:

`docs/api/saxo/balance-fields.md` は Saxo の `UnrealizedPositionsValue` について
公式定義 "The current unrealized profit/loss and face value..." を正確に引用し、
その直下に「本プロジェクトでの推奨: 含み損益確認」と書いていた。
定義文の "and face value" 側が実体で、この field は
**建玉の時価 − 決済コスト**である。実測:

| 量 | 値 |
|---|---|
| `UnrealizedPositionsValue` | 449,931 円 |
| `NonMarginPositionsValue + CostToClosePositions` | 449,931.42 円（一致） |
| 実際の含み損益 `ProfitLossOnTradeInBaseCurrency` | **-28,200 円**（478,131 円ずれる） |

含み損益として読めば符号も桁も誤る。誤りは 2026-04 の初回記載（commit 9280df4、
その commit 自身のタイトルが「外部 API field 規律一般化」）から
2026-09-01 まで無修正だった。

同じ測定で 2 件が追加で判明した。`PositionView.CurrentPrice` /
`MarketValue` / `Exposure` は market closed かつ購読なしで `0.0` を返す
（現値として使えば除算は例外、比較は黙って誤判定）。
`ProfitLossOnTradeInBaseCurrency` は建玉時の為替レートで換算され為替変動を含まない
（K-066 が実現損益で記録した穴と同型で、含み損益側は未記録だった）。

Saxo field の既往不具合はいずれも実データが食い違って初めて発覚している:
ed2b793（FieldGroups 不足）/ 68a2f0a（IFD-OCO 保護脚の取りこぼし、issue#16）/
72501f4（空レスポンスの形状）/ K-066 / K-069 / K-031 / 0bb1055。
**doc レビューで発見された例は 1 件も無い。**

`balance-fields.md` の 38 field のうち実例・観測値を持つのは約半分で、
`UnrealizedPositionsValue` は持たない側だった。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A. doc に「実測値を書く」ルールを足すだけ | 軽い | 実測値は書いた時点の snapshot。次に誰も再検証しない。今回の誤りも「実例を書く」ルールでは防げるが「書き忘れ」を検出できない | 不採用 |
| B. field の意味を**恒等式**として test に固定し、live 生 payload の fixture に対して検定する | 壊れたら CI で落ちる。仕様変更と解釈違いの両方を検出。doc の記述と test が乖離したら test が正 | fixture の採取に live token が要る。観測できていない状態（複数建玉・margin・market open）はカバーされない | **採用** |
| C. 毎回 live API を叩いて検証 | 常に最新 | ネットワーク依存でテストが不安定。レート制限。口座状態に依存して assert が書けない | 不採用 |

## Decision

> **外部 API の field について「A は B を意味する」と書くときは、その意味を
> 恒等式として表現し、live から採取した生 payload の fixture に対して
> assert するテストを書く。** 散文の解釈だけを doc に書いて終わりにしない。
>
> 1. 生 payload を `tests/fixtures/<provider>_<対象>_<YYYYMMDD>.json` に採取する
>    （秘匿 field は `REDACTED` に置換）。採取時刻と口座・建玉の状態を `_note` に書く。
> 2. 意味を恒等式で書く。「`UnrealizedPositionsValue` は含み損益」ではなく
>    「`UnrealizedPositionsValue == NonMarginPositionsValue + CostToClosePositions`
>    が成立する」と書く。
> 3. **棄却した解釈も assert する**。今回なら「含み損益ではない」を
>    `assert pnl < 0 < unrealized_positions_value` として残す。
>    誤った解釈に戻ることを防ぐのは、正しい解釈の記述より反証の記述である。
> 4. `docs/api/<provider>/` には公式定義の citation に加えて **実測値と採取日**、
>    および解釈を訂正した場合は **訂正履歴** を書く。
> 5. アクセサ名は field の実体に合わせる。実体と違う名前を付けない
>    （`unrealized_pnl` → `unrealized_positions_value`）。

Saxo についての実装: `tests/test_saxo_field_semantics.py`、
fixture は `tests/fixtures/saxo_live_snapshot_20260901.json`。

## Rationale

公式定義の引用は解釈の検証にならない。定義文が曖昧・複合的な場合
（"profit/loss **and** face value" のように 2 つの概念を並記する場合）はなおさらで、
引用した本人が「読みたい方」を採る余地が残る。恒等式は数値で反証可能なので、
その余地が無い。

「実測値を doc に書く」（選択肢 A）では不足である。実測値は書いた時点の snapshot で、
API 仕様が変わっても doc は黙って古いままになる。恒等式を test にすれば、
仕様変更は CI で落ちる。

反証の assert（Decision 3）を要求するのは、今回の誤りが
「正しい解釈が書かれていなかった」のではなく
「誤った解釈が正しい citation の隣に並んでいた」形だったため。
正しい記述を足すだけでは、誤った読みへの引力は消えない。

## Consequences

- **反映先**: `CLAUDE.md`（外部 API 統合の節）、`docs/api/TEMPLATE.md`、
  `docs/code-review-checklist.md`。
- **トレードオフ**: fixture 採取に live token が要るため、新 provider の field を
  documentation だけ先に書いて後から検証する、が許されなくなる。
  実 payload を採るまで「意味が確定した」と書けない。これは意図した制約である。
- **カバレッジの限界**: `saxo_live_snapshot_20260901.json` は
  1 口座・1 建玉・market closed・現金建玉のみ。**複数建玉、margin 建玉（CFD/FX）、
  market open 時、含み益が正の状態は未観測**。これらを観測したら fixture を追加し、
  同じ恒等式が成立するか確かめる。特に `CostToClosePositions` は建玉数に依存するため、
  複数建玉での恒等式は未検証である。
- **見直しトリガー**: Saxo が balance/position の field を追加・改名した時
  （`test_no_new_undocumented_fields` が落ちる）。
  他 provider（Tiingo/FRED/yfinance）に同じ規律を広げるかは、
  それぞれで field 誤読が実害を出した時点で判断する（今は Saxo のみ必須）。
