# ADR-023: 学習ドリルシステムの新設

- Status: accepted
- Date: 2026-04-16 (initial) / 2026-04-17 (refactor to independent)

## Context

ユーザーが Master Sensei のレポートで頻出する金融・投資用語の理解に苦労しており、体系的な学習教材が必要だった。2026-04-16 に 17 用語の診断で A=2/B=5/C=11 が判明。

## Decision

**Master Sensei と独立したドリルアプリを `learning/` 配下に新設する**。

アプリ自体の詳細な設計判断 (スケジューラ、質問バンク形式、採点方式、DB 独立化等) は `learning/docs/adr/` で独立系列として管理する。

## Scope

- コード: `learning/` (top-level、`src/learning/` からは 2026-04-17 に移動)
- DB: `learning/data/drill.duckdb` (sensei.duckdb と独立)
- エントリポイント: `drill.py` (repo root、3 行)
- Claude 側 integration: `.claude/skills/learn-status/`

## See also

- [learning/docs/adr/README.md](../../learning/docs/adr/README.md) — アプリ内部の ADR 索引
- [learning/docs/adr/001-scheduler-leitner.md](../../learning/docs/adr/001-scheduler-leitner.md)
- [learning/docs/adr/002-question-bank-markdown.md](../../learning/docs/adr/002-question-bank-markdown.md)
- [learning/docs/adr/003-grading-self-rubric.md](../../learning/docs/adr/003-grading-self-rubric.md)
- [learning/docs/adr/004-db-independence.md](../../learning/docs/adr/004-db-independence.md)
- [learning/docs/history/2026-04-17-v0.1-mvp.md](../../learning/docs/history/2026-04-17-v0.1-mvp.md) — 構築ジャーニー
- [learning/docs/curriculum.md](../../learning/docs/curriculum.md) — Stage 1-4 設計

## Consequences

- 親プロジェクトの ADR 番号連続性を維持 (023 として残す)
- アプリ内部の設計議論は learning/docs/adr/ に閉じる (別系列)
- 初版の DB 統合判断は learning/docs/adr/004 で supersede 済
