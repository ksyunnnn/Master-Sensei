# ADR-004: DB independence from sensei.duckdb

- Status: accepted
- Date: 2026-04-17
- Supersedes: (部分的に) ADR-023 @ master_sensei の DB 統合判断

## Context and Problem Statement

初版 (2026-04-16) では sensei.duckdb に `learning_*` テーブルを相乗りさせていた。ユーザーから「学習アプリは既存の仕組みと性質が異なるので完全に独立させたい。ソースコードも DB も」という要求。

## Decision Drivers

- 市場データ (sensei.duckdb) と学習データはライフサイクルが逆転 (市場 = 毎日更新、学習 = attempts 追加のみ)
- 学習 DB の配布・削除・リセットが独立で行えるべき (drill.duckdb を消せば学習状態クリア)
- master_sensei のバックアップ戦略と学習データのバックアップ戦略は分けた方がよい
- 初版決定 (相乗り) を撤回する形になるため、新規 ADR で明示

## Considered Options

- **完全独立 DB** (`learning/data/drill.duckdb`)
- **相乗り継続** (`sensei.duckdb` の `learning_*` テーブル)
- **Schema 分離 on same DB** (DuckDB の schema 機能で `learning.questions` 等)

## Decision Outcome

**`learning/data/drill.duckdb` の独立 DB を採用**。

sensei.duckdb から `learning_*` テーブルを drop、コードを `src/learning/` → `learning/` に移動、`src.db` への Python import を切って `learning/timeutil.py` としてローカル複製。

### Consequences

- 良い面: ライフサイクル分離、配布容易、concern 完全分離
- 悪い面: Claude の既定 MCP DuckDB 接続が sensei.duckdb のみ → `/learn-status` Skill では明示パス指定に変更
- 見直しトリガー: 学習結果と市場イベント (例: scan-market 登録イベント) を相関分析したい要求が出た場合、読み取り専用で両 DB を attach する方式を検討

## Pros and Cons of the Options

### 完全独立 DB
- Pros: 関心分離、バックアップ / 削除独立、テスト容易
- Cons: MCP 既定接続から外れる (明示パスで OK)

### 相乗り継続
- Pros: 単一 SoT、MCP 既定接続で即クエリ
- Cons: ユーザー要求違反、concern 混在、ライフサイクル逆転問題

### Schema 分離 on same DB
- Pros: 中間的、単一ファイル
- Cons: DuckDB schema 運用の学習コスト、結局ライフサイクル問題は解決せず

## Migration

- 2026-04-16: `sensei.duckdb` に `learning_questions` / `learning_attempts` / `learning_mastery` + sequence を作成
- 2026-04-17: これらを全 drop、`learning/data/drill.duckdb` で再作成
- 質問は Markdown が SoT なので `--reload` で auto-populate

ユーザー試用中の attempt データはこの refactor 前に `DELETE FROM learning_attempts` 済みだったため、データロスなし。

## References

- [ADR-023 @ master_sensei](../../../docs/adr/023-learning-drill-system.md) (初版判断の記録)
- history: `../history/2026-04-17-v0.1-mvp.md`
