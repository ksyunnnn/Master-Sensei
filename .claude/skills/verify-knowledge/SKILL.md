---
name: verify-knowledge
description: stale知見（180日以上未検証）を取得し、1件ずつ有効性を確認して検証日を更新する
---

stale知見の検証ワークフローを実行してください。

## 手順

1. `src/db.py` の `SenseiDB` を使ってstale知見を取得する:
   ```python
   import duckdb
   from src.db import SenseiDB
   conn = duckdb.connect("data/sensei.duckdb")
   db = SenseiDB(conn)
   stale = db.get_stale_knowledge()
   ```

2. stale知見が0件なら「検証が必要な知見はありません」と報告して終了する。

3. 各知見について以下を行う:
   - ID、カテゴリ、内容、根拠、信頼度、最終検証日を表示する
   - 現在の市場データと照合して、有効性の評価を提示する
   - ユーザーに判断を確認する: **有効（検証日更新）/ 修正 / 無効化**

4. ユーザーの判断に基づいて更新する:
   - 有効 → `db.update_knowledge_status(knowledge_id, "validated")`
   - 修正 → `db.add_knowledge()` で内容を更新（upsert）
   - 無効化 → `db.update_knowledge_status(knowledge_id, "invalidated", reason="...")`

5. 全件完了後、処理結果のサマリーを表示する。

## 注意事項

- ADR-003のWrite基準に従うこと
- 無効化された知見は削除せず、invalidation_reasonを記録して残す（Charter 5.2）
- SQLは直接書かず、SenseiDBのメソッドを使用する（ADR-008）
