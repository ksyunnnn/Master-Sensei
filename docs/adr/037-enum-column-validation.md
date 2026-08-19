# ADR-037: 列挙カラムを書き込み口で固定する（knowledge.category の drift 是正）

Status: accepted
Date: 2026-08-20

## Context

2026-08-20 の DB 監査で `events.id=330` の `status` が `'active'` になっているのを検出した。
`unreviewed` でも `reviewed` でもないため `/review-events` のレビュー待ち行列から消え、
2026-07-21 のアジア半導体リリーフラリーが未レビューのまま埋もれていた。
`update_event_status()` にバリデーションが無く任意の文字列を受け付けていたのが原因。

調べると、これは単発のミスではなかった。

**`knowledge.category` は検証が一切なく、15 種に drift していた。**

| 旧 category | 件数 |
|---|---|
| market_pattern | 19 |
| meta | 13 |
| risk_management | 9 |
| market | 5 |
| market_structure / microstructure / process | 各 4 |
| instrument | 3 |
| reference / regime / attribution | 各 2 |
| pattern / signal / strategy / reasoning | 各 1 |

`market` / `market_pattern` / `market_structure` / `pattern` は境界が定義されておらず、
書き手がその場で選んでいた。drift は現在進行形で、2026-08-20 に K-071 を起票した際も
`microstructure` を規定なしに選んでいる。

害は検索の信頼性である。category で絞ると関連知見を取りこぼす
（例: 平均回帰の知見が K-029 は `market_structure`、K-046 は `market_pattern`、
K-068 は `market` に分散していた）。

`events.category` にも 6 分類外の `corporate_action` が 1 件あるが、
これは 6 分類が文書化される前の手動登録行（2026-03-05、SOXS 1:20 リバーススプリット）で、
進行中の漏れではない。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A. 現状維持（規約のみ） | 変更ゼロ | drift が続く。CLAUDE.md の「SQL は SenseiDB にのみ書く」は規約であって機構ではない | 不採用 |
| B. DB に CHECK 制約を張る | ad-hoc SQL も守れる | 分類を変えるたびにスキーマ変更（ADR → テスト → 実装）が要る。分類はまだ育つ段階 | 今回は不採用 |
| C. 書き込み口（SenseiDB メソッド）で列挙を強制 | `trades.status` / `knowledge.verification_status` と同じ既存パターン。分類変更が安い | ad-hoc SQL は依然素通り | **採用** |

## Decision

> `knowledge.category` を **7 分類**に固定し、`SenseiDB` の書き込み口で列挙を強制する。
> `events.category` / `events.status` も同様に列挙で固定する。
> 既存 71 件の knowledge は新分類へ移行する。

### knowledge.category（7分類）

| category | 意味 | 件数 |
|---|---|---|
| `market_pattern` | X が Y を予測するか等、市場の反復挙動・統計的性質 | 28 |
| `meta` | 自分の推論・バイアス・予測の質・方法論 | 14 |
| `risk_management` | サイジング・stop・利確・ラダー | 10 |
| `microstructure` | 執行・板・時間帯・コスト・約定の実務 | 9 |
| `reference` | データソース・API・ツールの事実 | 5 |
| `attribution` | 急落/急騰の原因帰属の判定法 | 3 |
| `regime` | レジーム区分そのものの性質 | 2 |

`market_pattern` と `microstructure` の境界: **「X が Y を予測するか」は `market_pattern`、
「そもそも執行できるか・いくら掛かるか」は `microstructure`**。
例えば K-017（プレの方向は正規を予測しない）は `market_pattern`、
K-070（プレ気配は板が枯れて使えない）は `microstructure`。

### events.category

`scan-market` が生成する 6 分類 + 手動登録用 `corporate_action` の 7 種。

### events.status

`unreviewed` / `reviewed` / `dismissed` の 3 種（commit 6dcb899 で先行実装）。

## Rationale

**なぜ category の付け替えが ADR-018 に反しないか**: ADR-018 が禁じるのは
判断の事後書き換え（impact や reasoning を結果を見てから直すこと）である。
category は**どの棚に置くかの索引ラベル**であって市場判断ではない。
移行では `content` / `evidence` / `confidence` / `verification_status` を一切触っていない。
可逆性のため旧→新の全対応を `037-category-mapping.tsv` に保存した。

**なぜ CHECK 制約を今張らないか**: 分類はまだ育つ段階で、
`attribution`（3件）や `regime`（2件）が独立した棚として残るべきかは運用してみないと分からない。
スキーマに焼くと変更コストが高くつく。ad-hoc SQL の迂回路が残る点は
承知の上で、まず書き込み口を固める。

## Consequences

- **反映先**: `src/db.py`（`KNOWLEDGE_CATEGORIES` / `EVENT_CATEGORIES` /
  `EVENT_STATUSES` / `set_knowledge_category()`）、`docs/adr/037-category-mapping.tsv`
- **トレードオフ**: ad-hoc python で RW 接続を開いて直接 `UPDATE` する経路は依然開いている。
  この層を塞ぐには CHECK 制約が要る（上記の理由で見送り）。
- **新しい分類が要ると判断したら**、`KNOWLEDGE_CATEGORIES` に足す前に
  既存 7 種のどれにも入らないことを確認する（安易に足すと drift の再来になる）。
- **見直しトリガー**:
  - `attribution` / `regime` が 5 件を超えず、かつ他分類との境界が曖昧なままなら統合を検討する
  - ad-hoc SQL 起因の不正値が再び観測されたら CHECK 制約へ倒す
- 未処理として残る点: `events.impact` / `events.relevance` / `knowledge.confidence` /
  `trades.direction` は依然未検証。実データは清潔だが、
  それはスキルが固定リテラルを渡しているためで機構に守られてはいない。
