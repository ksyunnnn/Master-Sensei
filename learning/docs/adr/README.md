# Architectural Decision Records (learning app)

MADR 形式 (Markdown Architectural Decision Records)。1 ADR = 1 判断、事後編集禁止、変更時は新 ADR で supersede。

## Index

| # | Title | Status | Date |
|---|-------|--------|------|
| [001](001-scheduler-leitner.md) | Scheduler: Leitner 5-box | Accepted | 2026-04-16 |
| [002](002-question-bank-markdown.md) | Question bank: Markdown + loader | Accepted | 2026-04-16 |
| [003](003-grading-self-rubric.md) | Grading: Self-rating + rubric reveal | Accepted | 2026-04-16 |
| [004](004-db-independence.md) | DB independence from sensei.duckdb | Accepted | 2026-04-17 |

## Process

1. 新規判断が必要になったら `TEMPLATE.md` をコピーして通し番号を振る (`001-xxx.md`)
2. Context / Decision Drivers / Options / Outcome / Consequences を埋める
3. Status = proposed でコミット → 実装完了したら accepted
4. 判断を変える場合は**既存 ADR を編集せず**、新規 ADR で `supersedes ADR-NNN` を明示
5. 親プロジェクト (master_sensei/docs/adr/) とは独立系列。相互参照は明示リンクで

## Relation to parent-project ADRs

- Master Sensei の ADR-023 が「学習ドリルシステムを作る」というメタ判断を記録
- このアプリ固有の実装判断 (スケジューラ選定 等) は本 ADR 系列に格納
- 二重管理を避けるため、master_sensei 側 ADR-023 は最小スタブ + 本 index への pointer
