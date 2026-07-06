# ADR-XXX: タイトル

Status: proposed | accepted | deprecated | superseded by ADR-YYY
Date: YYYY-MM-DD

> **ADR運用ルール（Nygard慣行）**: accepted な ADR の substance は後から書き換えない（immutable）。結論を変える必要が出たら、**新しい ADR を起こして古い方を supersede** する ── 古い ADR の Status を `superseded by ADR-YYY` に更新し、新 ADR 冒頭に `Supersedes: ADR-XXX` を記す。substance は書き換えず残す。書き換えてよいのは typo 修正・注記のみ。この不変性こそが決定履歴の信頼性の source（accepted を編集し始めると「いつ何が決まっていたか」が失われる）。前例: ADR-005 → ADR-009 が supersede。部分的な変更でも「都合よく本文を直す」のではなく新 ADR で行う。
> 出典: Nygard "Documenting Architecture Decisions" / Fowler bliki "Architecture Decision Record"。

## Context

なぜこの決定が必要になったか。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A | ... | ... | 採用/不採用 |
| B | ... | ... | 採用/不採用 |

## Decision

> 確定内容を引用ブロックで明示

## Rationale

選択の根拠。公式ドキュメントへの参照を含む。

## Consequences

- 反映先
- トレードオフ
- 将来の見直しトリガー
