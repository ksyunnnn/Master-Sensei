---
name: scan-market
description: WebSearchで最新のニュース・市場動向を調査し、イベントをDBに登録する。地政学・FRB・半導体・原油・関税・市場動向の6カテゴリを網羅的に調査する。
---

市場ニュースの調査・イベント登録を実行してください。

## タイムゾーン

現在時刻(JST): !`python3 -c "from datetime import datetime, timezone, timedelta; jst=timezone(timedelta(hours=9)); print(datetime.now(tz=jst).strftime('%Y-%m-%d %H:%M JST'))"`

すべてのevent_timestampは **JST (Asia/Tokyo)** で記録する。

```python
from src.db import JST  # timezone(timedelta(hours=9))
```

- OK: `datetime(2026, 3, 28, 15, 0, tzinfo=JST)`
- NG: `datetime(2026, 3, 28, 15, 0)` ← naive、_require_awareでエラー

## 品質基準

### ソース管理
- 記憶に基づく登録は禁止。必ずWebSearchの検索結果からURLと事実を取得してから登録する
- ソースTier: Tier 1（政府・企業IR・国際機関）> Tier 2（Reuters, AP, CNBC, CNN, NPR, Al Jazeera, BBC）> Tier 3（個人ブログ・SNS・無名サイト）
- **Tier 3ソースのイベントは登録不可**

### 検証ルール
- **定性イベント（戦争・政策等）**: 2つ以上の独立したTier 1-2ソースで確認できたもののみ登録。1ソースのみの情報は登録しない
- **定量データ（VIX・原油価格等）**: Parquetの値と照合可能な場合は照合する。WebSearch値とParquet値が矛盾する場合は不採用
- 検索結果の日付（年を含む）とイベント日付が一致することを確認する
- 固有名詞（作戦名、法律名、人名等）は検索結果の表記をそのまま使用する
- 検証レベルをimpact_reasoningに含める（例: 「FRB公式声明で確認」「CNBC+NPRで報道」）

## 手順

### 1. 前回実行の確認と調査対象期間の決定

前回の`/scan-market`実行時刻を取得し、調査対象期間を決定する。

```bash
python -c "
import duckdb
from src.db import SenseiDB
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)
last = db.get_last_skill_execution('scan-market')
if last:
    print(f'前回実行: {last[\"executed_at\"]}')
    print(f'結果: {last[\"result_summary\"]}')
    if last.get('metadata'):
        print(f'メタデータ: {last[\"metadata\"]}')
else:
    print('初回実行（前回記録なし）→ 直近7日間を対象')
conn.close()
"
```

- 前回記録あり → 前回の`executed_at`以降のニュースを調査
- 前回記録なし → 直近7日間を調査

### 2. 既存イベントの確認

重複登録を防ぐため、直近のイベントを確認する。

```bash
python -c "
import duckdb
from src.db import SenseiDB
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)
events = db.get_active_events()
print(f'=== 登録済みイベント ({len(events)}件) ===')
for e in events[:10]:
    print(f\"  [{e['category']}] {e['event_timestamp']} {e['summary'][:60]}\")
conn.close()
"
```

### 3. 過去のlessonを確認

impact判定の前に、過去のevent_reviewsで修正があったもの（lesson）を参照する。

```bash
python -c "
import duckdb
from src.db import SenseiDB
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)
reviews = conn.execute('''
    SELECT e.category, e.summary, er.original_impact, er.revised_impact, er.lesson
    FROM event_reviews er
    JOIN events e ON er.event_id = e.id
    WHERE er.original_impact != er.revised_impact
    ORDER BY er.review_date DESC LIMIT 5
''').fetchdf().to_dict('records')
if reviews:
    print('=== 過去のimpact修正 ===')
    for r in reviews:
        print(f\"  [{r['category']}] {r['summary'][:50]}\")
        print(f\"    {r['original_impact']} -> {r['revised_impact']}: {r['lesson']}\")
else:
    print('lesson記録なし（初回）')
conn.close()
"
```

### 4. WebSearchでニュース調査

以下の6カテゴリについて、手順1で決めた対象期間のニュースをWebSearchで調査する。

1. **地政学リスク** — 戦争・制裁・紛争（Iran, Middle East等）
2. **FRB・金融政策** — 利上げ/利下げ・インフレ・雇用
3. **半導体セクター** — NVIDIA, AMD, SOX index, TSMC
4. **原油・エネルギー** — Brent, WTI, Strait of Hormuz
5. **関税・通商政策** — Section 232, Section 301, tariffs
6. **米国株式市場** — S&P 500, Nasdaq, VIX, sector rotation

各カテゴリで最低1回はWebSearchを実行する。

### 5. イベント登録

調査結果から、対象シンボル（TQQQ/SOXL/TECL/SPXL等）の価格に影響しうるイベントを登録する。

ADR-003 Write基準:
- 対象シンボルの価格に影響しうるイベントのみ登録
- スコープ外（個別株、仮想通貨等）は登録しない
- 既存イベントと重複する場合は登録しない

カラム仕様:
- `event_timestamp`: datetime with tzinfo=JST（必須）
- `category`: geopolitical / fed / semiconductor / oil / tariff / market
- `impact`: positive / negative / neutral
- `relevance`: direct（半導体直撃）/ indirect（マクロ経由）/ background（遠因）
- `source`: 必ず `'scan-market'` を指定

```bash
python -c "
import duckdb
from datetime import datetime
from src.db import SenseiDB, JST
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)
db.add_event(
    event_timestamp=datetime(2026, 3, 28, 15, 0, tzinfo=JST),
    category='geopolitical',
    summary='イベントの1行サマリ',
    impact='negative',
    impact_reasoning='なぜその影響度か（1文）',
    relevance='direct',
    source_url='https://...',
    source='scan-market',
)
print('Event added')
conn.close()
"
```

複数イベントがある場合は1つのスクリプト内で複数回 `db.add_event()` を呼ぶ。
**重要**: inline Pythonスクリプト内で `#` コメントを使わないこと（Bashのセキュリティ警告が出る）。

### 6. 実行記録と調査報告

イベント登録後、実行履歴をskill_executionsに記録する。

```bash
python -c "
import json
from datetime import datetime
import duckdb
from src.db import SenseiDB, JST
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)
db.record_skill_execution(
    skill_name='scan-market',
    executed_at=datetime.now(tz=JST),
    result_summary='N events added',
    metadata=json.dumps({
        'latest_source_date': '検索結果の最新記事日時（ISO 8601）',
        'categories_searched': ['geopolitical', 'fed', 'semiconductor', 'oil', 'tariff', 'market'],
    }),
)
conn.close()
"
```

以下のフォーマットで報告する。

```
## 調査報告
- 調査実施: {現在時刻 JST}
- 調査対象: {前回実行時刻 JST} 〜 現在（初回の場合は「直近7日間」）
- 取得できた最新情報: {検索結果で最も新しい記事の日時とソース名}
- 登録イベント: {N}件
- スキップ（重複/スコープ外）: {M}件

### 登録イベント一覧
| 日時(JST) | カテゴリ | サマリ | impact | ソース |
|-----------|---------|--------|--------|--------|
| ... | ... | ... | ... | ... |

### 市場環境の要約
{6カテゴリの調査結果を2-3文で要約}

Sources:
- [Source Title](URL)
- ...
```

## 注意事項

- SQLは直接書かず、SenseiDBのメソッドを使用する（ADR-008）
- event_timestampは必ずJST timezone-awareで記録する
- イベント登録時は `source='scan-market'` を必ず指定する
- 「取得できた最新情報」は実際の検索結果の最新記事日時を正直に記載する（推測しない）
- 実行完了後は必ず `record_skill_execution()` を呼んで履歴を記録する
