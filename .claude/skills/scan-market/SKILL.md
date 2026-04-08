---
name: scan-market
description: WebSearchで最新のニュース・市場動向を調査し、イベントをDBに登録する。地政学・FRB・半導体・原油・関税・市場動向の6カテゴリを網羅的に調査する。
---

市場ニュースの調査・イベント登録を実行してください。

## タイムゾーン

まず現在時刻を確認する: `TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M JST'`

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

### impact判定のバイアス補正
review-eventsでscan-market登録イベントの**51%がnegative→neutralに修正**された（session 14, 41件中21件）。戦時エスカレーション系イベントに対する系統的ネガティブバイアスが確認されている。

以下に該当するイベントは **impact=neutral** をデフォルトとする:
- K-024対象: ミサイル交換・空爆・IRGC声明など進行中の戦争の繰り返しイベント
- K-009対象: Trump SNS/演説での最後通牒・脅迫（裏チャネル交渉と並行する修辞パターン）
- 迎撃成功パターン: サウジ/UAE/カタール防空による攻撃迎撃
- 攻撃宣言不実行: 期限付き脅迫→期限経過→実行なし

negativeにするのは: 供給に実被害があった場合、米軍KIA発生、レジーム変化を伴うイベントのみ

## 手順

### 1. 前回実行・既存イベント・過去lessonの一括確認

前回実行時刻の取得、既存イベントの重複チェック、過去のlesson参照を**1回のスクリプト**で行う。

```bash
python << 'PYEOF'
import duckdb
from src.db import SenseiDB

conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)

# 前回実行
last = db.get_last_skill_execution('scan-market')
if last:
    print(f'前回実行: {last["executed_at"]}')
    print(f'結果: {last["result_summary"]}')
    if last.get('metadata'):
        print(f'メタデータ: {last["metadata"]}')
else:
    print('初回実行（前回記録なし）→ 直近7日間を対象')

# 既存イベント
events = db.get_active_events()
print(f'\n=== 登録済みイベント ({len(events)}件) ===')
for e in events[:10]:
    print(f"  [{e['category']}] {e['event_timestamp']} {e['summary'][:60]}")

# 過去のlesson
reviews = db.get_impact_lessons(limit=5)
if reviews:
    print('\n=== 過去のimpact修正 ===')
    for r in reviews:
        cat = r.get('category')
        sm = r.get('summary', '')[:50]
        oi = r.get('original_impact')
        ri = r.get('revised_impact')
        ls = r.get('lesson')
        print(f'  [{cat}] {sm}')
        print(f'    {oi} -> {ri}: {ls}')
else:
    print('\nlesson記録なし（初回）')

conn.close()
PYEOF
```

- 前回記録あり → 前回の`executed_at`以降のニュースを調査
- 前回記録なし → 直近7日間を調査

### 2. WebSearchでニュース調査

以下の6カテゴリについて、手順1で決めた対象期間のニュースをWebSearchで調査する。

1. **地政学リスク** — 戦争・制裁・紛争（Iran, Middle East等）
2. **FRB・金融政策** — 利上げ/利下げ・インフレ・雇用
3. **半導体セクター** — NVIDIA, AMD, SOX index, TSMC
4. **原油・エネルギー** — Brent, WTI, Strait of Hormuz
5. **関税・通商政策** — Section 232, Section 301, tariffs
6. **米国株式市場** — S&P 500, Nasdaq, VIX, sector rotation

各カテゴリで最低1回はWebSearchを実行する。

### 3. イベント登録

#### 3a. impact判定前のlesson照合（K-027）

各イベントのimpactを決める**前に**、手順1で取得したlessonを照合する。

- negativeを付与しようとするイベントについて、同カテゴリの過去lesson（neg→neu修正）がないか確認する
- 修正パターンが存在する場合、そのlessonの理由が今回にも当てはまるか判断する
- 当てはまる場合はneutralに変更し、impact_reasoningに「lesson照合: [lesson要約]」を含める
- 当てはまらない場合はnegativeを維持し、impact_reasoningに「lesson照合済み: [なぜ今回は異なるか]」を明記する

#### 3b. 登録

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
python << 'PYEOF'
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
PYEOF
```

複数イベントがある場合は1つのスクリプト内で複数回 `db.add_event()` を呼ぶ。
**重要**: heredoc方式（`python << 'PYEOF'`）を使用すること。`python -c "..."` + `f\"` パターンやトリプルクォート（`'''` / `"""`）はobfuscation検出警告が出る（詳細: `~/.claude/CLAUDE.md`）。

### 4. 実行記録と調査報告

イベント登録後、実行履歴をskill_executionsに記録する。

```bash
python << 'PYEOF'
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
PYEOF
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
- impact_reasoningには具体的なポジション影響シナリオを含める（例: 「SOXLロングなら○○、SOXSなら○○」）。特に急反転リスクのあるイベント（関税停止、停戦合意等）はK-009パターンとの照合を明示する
