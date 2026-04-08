---
name: scan-market-quick
description: 市場ニュースの簡易スキャン。2回のWebSearchで全6カテゴリを広く浅く調査し、深掘りが必要なカテゴリをフラグする。急ぎの時に使う。
---

市場ニュースの**簡易スキャン**を実行してください。通常版（`/scan-market`）と異なり、広く浅くスキャンして深掘りポイントを提示する。

## タイムゾーン

まず現在時刻を確認する: `TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M JST'`

すべてのevent_timestampは **JST (Asia/Tokyo)** で記録する。

```python
from src.db import JST  # timezone(timedelta(hours=9))
```

## 通常版との違い

| 項目 | quick | 通常版 |
|------|-------|--------|
| WebSearch回数 | 2回 | 6回以上 |
| カテゴリ別深掘り | しない | する |
| イベント登録 | 確実なもののみ | 網羅的 |
| ソース検証 | 1ソースでOK（ただしTier 1-2限定） | 定性は2ソース必須 |
| 深掘りフラグ | 出す | 不要 |
| 所要時間目安 | ~1分 | ~3分 |

## 品質基準

通常版より緩和するが、最低限は守る:
- 記憶に基づく登録は禁止。WebSearch結果からのみ登録
- Tier 3ソース（個人ブログ・SNS）のイベントは登録不可
- 1ソースでも登録可。ただし**Tier 1-2に限る**
- 不確実なものは登録せず、深掘りフラグで報告する

## 手順

### 1. 既存イベント確認

```bash
python << 'PYEOF'
import duckdb
from src.db import SenseiDB

conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)

# 前回実行（scan-market / scan-market-quick どちらも確認）
for skill in ['scan-market', 'scan-market-quick']:
    last = db.get_last_skill_execution(skill)
    if last:
        print(f'{skill} 前回: {last["executed_at"]}')

# 既存イベント（重複チェック用）
events = db.get_active_events()
print(f'\n登録済み: {len(events)}件')
for e in events[:5]:
    print(f"  [{e['category']}] {e['summary'][:60]}")

conn.close()
PYEOF
```

### 2. WebSearch（2回のみ）

以下の2クエリで6カテゴリを広くカバーする。**クエリは毎回その時点の市場状況に合わせて組む**こと（固定テンプレートは使わない）。

**検索1**: 地政学・関税・原油をカバーする検索
**検索2**: FRB・半導体・米国株市場をカバーする検索

各検索で、6カテゴリのどれに該当するニュースがあるかを意識しながら結果を読む。

### 3. トリアージと登録

検索結果を以下の3つに分類する:

- **登録**: 確実にレバETFに影響する。ソースがTier 1-2。→ イベント登録する
- **深掘りフラグ**: 影響がありそうだが情報不足、または重大だが詳細不明 → 登録せず報告
- **スキップ**: スコープ外、既存と重複、影響軽微 → 何もしない

イベント登録は通常版と同じ方式:

```bash
python << 'PYEOF'
import duckdb
from datetime import datetime
from src.db import SenseiDB, JST
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)

# 全イベントを1回で登録
db.add_event(
    event_timestamp=datetime(2026, 4, 2, 15, 0, tzinfo=JST),
    category='geopolitical',
    summary='イベントの1行サマリ',
    impact='negative',
    impact_reasoning='簡易スキャン: [1文の理由]',
    relevance='direct',
    source_url='https://...',
    source='scan-market-quick',
)
# db.add_event(...) 複数あれば続ける

conn.close()
PYEOF
```

**重要**: `source='scan-market-quick'` を指定して通常版と区別する。

### 4. 報告

```
## 簡易スキャン報告
- 実施: {現在時刻 JST}
- 登録: {N}件
- スキップ: {M}件

### 登録イベント
| 日時(JST) | カテゴリ | サマリ | impact |
|-----------|---------|--------|--------|
| ... | ... | ... | ... |

### 深掘りフラグ
| カテゴリ | 概要 | 理由 |
|---------|------|------|
| fed | FRB議事録に新たな言及 | 詳細不明、原文未確認 |
| oil | ホルムズ海峡関連報道 | 1ソースのみ、影響度不明 |

→ 深掘りが必要な場合は `/scan-market` を実行してください。

Sources:
- [Source Title](URL)
- ...
```

### 5. 実行記録

```bash
python << 'PYEOF'
import json
from datetime import datetime
import duckdb
from src.db import SenseiDB, JST
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)
db.record_skill_execution(
    skill_name='scan-market-quick',
    executed_at=datetime.now(tz=JST),
    result_summary='N events added, M flagged for deep scan',
    metadata=json.dumps({
        'flagged_categories': ['fed', 'oil'],
    }),
)
conn.close()
PYEOF
```

## 注意事項

- SQLは直接書かず、SenseiDBのメソッドを使用する（ADR-008）
- event_timestampは必ずJST timezone-awareで記録する
- 深掘りフラグは**出し忘れない**。「何もなかった」と「調べ切れなかった」は明確に区別する
- このスキルはトリアージが目的。判断に迷ったら登録せずフラグする
