# ADR-020: knowledgeテーブルへのリンク列・TLDR列追加

Status: accepted
Date: 2026-04-05

## Context

knowledge テーブル（25件蓄積）には次の課題がある:

1. **相互参照の不在**: K-009（戦時エスカレーション割引）, K-017（プレマーケット≠正規）, K-024 等のパターングループ関係が content 中の free-text 参照でのみ存在。SQL で「K-009 を参照する全ての知見」を辿れない。
2. **認知負荷の高さ**: `knowledge.content` を全文読まないと要点不明。scan-market/entry-analysis 実行時に「関連知見3件」を surface するコストが高い。

Obsidian PKM 原則（docs/references/obsidian-pkm-principles.md）の調査から:
- **Linking**: 双方向リンクは「予期せぬ隣接ノート」を surface する。SQL の backlink クエリで80%の価値を achievable。
- **Progressive Summarization**: 全ノートに秒単位で取り出せる圧縮形式（tldr）を持つ。100件スキャン時は tldr、行動時は content。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A. `related_knowledge_ids VARCHAR[]` (DuckDB native list) | 単純、1行で完結、クエリ容易 | 参照整合性なし（孤立ID許容） | **採用** |
| B. 別テーブル `knowledge_links(src, dst, relation_type)` | 参照整合性・関係種別付与可 | 26件規模には過剰、JOIN必須 | 不採用 |
| C. `tldr VARCHAR` カラム追加 | scan時コスト削減、常に内容連動 | content書換え時に手動更新必要 | **採用** |
| D. content冒頭をTLDRとして暗黙使用 | 列追加不要 | 規律が崩れやすい、確実性なし | 不採用 |

DuckDB の `VARCHAR[]` は native 型。`list_contains(related_knowledge_ids, 'K-009')` で backlink 検索可能。

## Decision

> knowledge テーブルに次の2列を追加する:
> - `tldr VARCHAR` — 1文の圧縮形式（推奨 50-100字）
> - `related_knowledge_ids VARCHAR[]` — 関連 knowledge_id のリスト
>
> 既存 DB には `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` でマイグレーション。
> `add_knowledge()` API に optional 引数として追加。
> `get_backlinks(knowledge_id)` メソッドで逆引き提供。

## Rationale

- **VARCHAR[]採用**: 26件規模では参照整合性の欠如より単純性が優る（Charter §3.5）。参照先削除時の orphan 発生可能性はあるが、knowledge は invalidated しても削除されない（ADR-003）ため実害なし。
- **tldr別列採用**: Progressive Summarization（Tiago Forte）の原則。content と独立して持つことで圧縮規律を強制。
- **方向性**: 単方向リンク（source が target を参照）。SQL backlink クエリで双方向価値を復元。相互に追記する運用負荷を避ける。

## Consequences

- **反映先**:
  - `src/db.py`: schema + migration + `add_knowledge()` 拡張 + `get_backlinks()` 追加
  - `tests/test_db.py`: migration テスト + link/tldr CRUD テスト
  - 既存25件のknowledgeには tldr バックフィル必要（別タスク、本ADRでは扱わない）
  - ADR-003 の現スキーマ照合表を更新: knowledge カラム数 11 → 13

- **トレードオフ**:
  - 参照整合性なし（存在しない K-XXX を related に入れても検出されない）
  - tldr と content の整合性は運用規律に依存

- **将来の見直しトリガー**:
  - knowledge が 100件超で関係種別が必要になったら → Option B (knowledge_links テーブル) に移行
  - orphan 参照が5件超で検出できないケースが問題化したら → 整合性チェック関数追加
