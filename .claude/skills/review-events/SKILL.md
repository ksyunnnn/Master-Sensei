---
name: review-events
description: 未検証イベントのimpact判定を事後検証し、lessonを記録する。3日以上経過したイベントが対象。
---

イベント事後検証を実行してください。

## タイムゾーン

現在時刻(JST): !`python3 -c "from datetime import datetime, timezone, timedelta; jst=timezone(timedelta(hours=9)); print(datetime.now(tz=jst).strftime('%Y-%m-%d %H:%M JST'))"`

## 手順

### 1. 未検証イベントの取得

3日以上経過した未検証イベントを取得する。

```bash
python -c "
import duckdb
from datetime import datetime, timedelta
from src.db import SenseiDB, JST
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)
cutoff = datetime.now(tz=JST) - timedelta(days=3)
events = conn.execute('''
    SELECT id, event_timestamp, category, summary, impact, impact_reasoning, source_url
    FROM events
    WHERE status = \'unreviewed\'
    AND event_timestamp < ?
    ORDER BY event_timestamp
''', [cutoff]).fetchdf().to_dict('records')
print(f'=== 検証対象: {len(events)}件 ===')
for e in events:
    print(f\"  #{e['id']} [{e['category']}] {e['event_timestamp']}\")
    print(f\"    {e['summary'][:70]}\")
    print(f\"    impact={e['impact']}: {e['impact_reasoning']}\")
    print(f\"    source: {e['source_url']}\")
    print()
conn.close()
"
```

対象が0件なら「検証対象なし」と報告して終了する。

### 2. 各イベントの事後検証

イベントごとに以下を実施する:

1. **WebSearchで実際の市場影響を確認** — イベント発生後の対象シンボル（SOXL/TQQQ等）の価格変動、市場の反応を調査
2. **original_impactと実績を比較**:
   - impact判定は正しかったか？
   - 影響の大きさは想定通りだったか？
   - 想定外の波及経路はあったか？
3. **lessonを1文で記録** — 同種のイベントが再発した際に参考になる知見

### 3. レビューの記録

```bash
python -c "
import duckdb
from datetime import date
from src.db import SenseiDB
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)

db.add_event_review(
    event_id=1,                          # 対象イベントのID
    review_date=date.today(),
    original_impact='negative',          # 登録時のimpact
    revised_impact='negative',           # 検証後のimpact（変更があれば修正）
    actual_outcome='SOXLが2日で-21%下落',  # 実際に何が起きたか
    lesson='VIX急騰+原油危機の同時発生は、半導体セクターへの影響が個別要因の合計より大きい',
)
print('Review added')
conn.close()
"
```

### 4. 報告

```
## 事後検証報告
- 検証実施: {現在時刻 JST}
- 対象イベント: {N}件

### 検証結果
| ID | サマリ | original | revised | lesson |
|----|--------|----------|---------|--------|
| ... | ... | ... | ... | ... |

### impact修正があったもの
{修正があった場合、なぜ判定を変えたかを説明}

### 発見した知見
{knowledge DBに記録すべき知見があれば提案する}
```

## 注意事項

- SQLは直接書かず、SenseiDBのメソッドを使用する（ADR-008）
  - ただし未検証イベントの取得クエリは `get_active_events()` にフィルタがないため、手順1のSQLは許容する
- lessonは将来の `/scan-market` 実行時に参照される。具体的かつ再利用可能な知見にする
- impact修正は正直に記録する。外れたこと自体は問題ではない（Charter 4.4）
