---
name: learn-status
description: 学習ドリル (ADR-023) の進捗をレビューしてカリキュラムを調整する。mastery progress と weak area を分析し、質問追加・修正・再編成を提案する。
---

# learn-status

学習ドリルの進捗を定期レビューして、カリキュラムをユーザーに合わせて調整するスキル。

## タイムゾーン

現在時刻確認: `TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M JST'`

## 手順

### 1. 進捗サマリと苦手分析を一括取得

```bash
python << 'PYEOF'
import duckdb
from learning.db import LearningDB

conn = duckdb.connect('learning/data/drill.duckdb')
db = LearningDB(conn)

s = db.mastery_summary()
print(f"=== 進捗サマリ ===")
print(f"  全質問数: {s['total_questions']}")
print(f"  学習済み: {s['seen']}")
print(f"  Mastered: {s['mastered']}")
print(f"  Box 分布: {s['box_distribution']}")
print(f"  Stage 進捗: {s['stage_breakdown']}")

print(f"\n=== 苦手トピック (attempt >= 2) ===")
for term, attempts, wrongs, score in db.weak_terms(min_attempts=2):
    print(f"  {term}: score {score}, {attempts} 回, 誤答 {wrongs}")

print(f"\n=== 直近 20 attempts ===")
for row in db.recent_attempts(limit=20):
    attempt_id, qid, term, at, rating, outcome = row
    print(f"  [{at}] {qid} {term}: {rating} ({outcome})")

conn.close()
PYEOF
```

### 2. 分析観点

取得データを以下の観点で分析する:

**(a) Mastery progression**
- 各 Stage の seen / total 比率
- 全体の mastered 率
- Box 1-4 の分布（1 に偏っていれば苦戦、高い box に散らばっていれば順調）

**(b) Weak area identification**
- weak_terms で score < 0.5 の用語を特定
- 誤答が 2 回以上ある term は「foundation 不足」の可能性
- 同じ term に複数の質問がある場合、特定の difficulty で詰まっているか確認

**(c) Gap detection**
- `learning_questions` テーブルに対して、scan-market レポートで最近使った用語のカバレッジを確認
- カバーされていない新出用語は `/learn-add-question` 相当で追加する

**(d) Stage promotion readiness**
- Stage 1 が 70% 以上 seen かつ 50% 以上 mastered なら Stage 2 解放推奨

### 3. ユーザーへの報告フォーマット

```
## 学習進捗レビュー (実施: {現在時刻 JST})

### 全体状況
- 全質問数: N
- Seen: M (X%)
- Mastered: K (Y%)
- 直近 N 日の attempt 数: ...

### Stage 別進捗
- Stage 1: seen/total = X/Y, mastered = Z
- Stage 2: ...

### 苦手トピック
| term | score | attempts | 推奨アクション |
|------|-------|----------|--------------|
| ... | ... | ... | foundation 強化 / 難易度下げた新問追加 / 等 |

### カリキュラム調整提案
1. {具体的な追加・修正・削除の提案 1}
2. ...
```

### 4. カリキュラム調整の実行（ユーザー承認後）

ユーザーが調整を承認した場合:

- **新規質問追加**: `learning/data/questions/stage_N/` に Markdown 追加 → 次回 drill.py 起動時に自動 load
- **既存質問修正**: 該当 .md を edit → 次回 load で upsert される
- **Stage 解放**: `learning/docs/curriculum.md` を更新 + Stage N の質問を `learning/data/questions/stage_N/` に配置

## 注意事項

- **週 1 目安**の実行を想定。過剰な調整は ADR-023 の "desirable difficulty" 原則を害する
- カリキュラム変更は `learning/docs/curriculum.md` に反映
- 新規質問追加時は prereqs を必ず明示（Stage 1 を踏んでから Stage 2、のような依存を崩さない）
- 質問修正は**解説の精緻化**中心。Prompt の根本変更は ID 採番し直して別問として追加する方が mastery データが clean
- スキル実行後は `condition.md` に学習進捗メモを 1-2 行追加する
