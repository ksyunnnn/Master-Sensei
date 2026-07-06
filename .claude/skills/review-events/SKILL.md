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
python << 'PYEOF'
import duckdb
from datetime import datetime, timedelta
from src.db import SenseiDB, JST
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)
cutoff = datetime.now(tz=JST) - timedelta(days=3)
sql = (
    "SELECT id, event_timestamp, category, summary, impact, impact_reasoning, source_url "
    "FROM events "
    "WHERE status = 'unreviewed' "
    "AND event_timestamp < ? "
    "ORDER BY event_timestamp"
)
events = conn.execute(sql, [cutoff]).fetchdf().to_dict('records')
print(f'=== 検証対象: {len(events)}件 ===')
for e in events:
    eid = e.get('id')
    cat = e.get('category')
    ts = e.get('event_timestamp')
    sm = e.get('summary', '')[:70]
    imp = e.get('impact')
    ir = e.get('impact_reasoning')
    url = e.get('source_url')
    print(f'  #{eid} [{cat}] {ts}')
    print(f'    {sm}')
    print(f'    impact={imp}: {ir}')
    print(f'    source: {url}')
    print()
conn.close()
PYEOF
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
python << 'PYEOF'
import duckdb
from src.db import SenseiDB, today_jst
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)

db.add_event_review(
    event_id=1,
    review_date=today_jst(),
    original_impact='negative',
    revised_impact='negative',
    actual_outcome='SOXLが2日で-21%下落',
    lesson='VIX急騰+原油危機の同時発生は、半導体セクターへの影響が個別要因の合計より大きい',
)
print('Review added')
conn.close()
PYEOF
```

### 4. チャネル台帳の保守（ADR-034 自己修正ループ）

review-events は events inclusion の**出口採点**として、チャネル台帳（`docs/event-channels.md`）を育てる役割を持つ。realized impact（実際に動いたか）は **台帳の保守にのみ** 使う ── inclusion には使わない（look-ahead 回避、ADR-034）。

各検証で、そのイベントが紐づくチャネル（impact_reasoning に記載）と、実績がそのチャネルの妥当性を支持したかを確認する。**累積した検証証拠**に基づき、必要なら台帳の編集を**提案**する（1イベントの結果で即断しない）:

- **昇格**: 台帳「候補チャネル」節の候補が、複数イベントで繰り返し有意な price impact を示した → 確定チャネルへ昇格を提案。
- **降格**: 確定チャネルのイベントが繰り返し price impact を示さない → 降格/削除を提案。
- **境界注記の更新**: 想定外の波及経路・誤分類が判明した → 該当チャネルの境界注記の修正を提案。

提案が妥当ならユーザー確認のうえ `docs/event-channels.md` を編集し、変更ログ節に理由を1行残す（git diff がドリフトの監査証跡になる）。台帳変更が無ければ「台帳変更なし」と報告する。

### 5. 報告

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

### チャネル台帳の保守（ADR-034）
{docs/event-channels.md の昇格/降格/境界注記の変更提案。無ければ「台帳変更なし」}
```

## 注意事項

- SQLは直接書かず、SenseiDBのメソッドを使用する（ADR-008）
  - ただし未検証イベントの取得クエリは `get_active_events()` にフィルタがないため、手順1のSQLは許容する
- lessonは将来の `/scan-market` 実行時に参照される。具体的かつ再利用可能な知見にする
- impact修正は正直に記録する。外れたこと自体は問題ではない（Charter 4.4）
- 検証結果のactual_outcomeには具体的なポジション影響を含める（例: 「SOXLロングなら-21%」）。抽象的なpositive/negativeだけでなく、次回のimpact判定精度向上に使える具体性を持たせる
- realized impact は events の inclusion 判定には使わず、**チャネル台帳（`docs/event-channels.md`）の保守にのみ**使う（ADR-034, look-ahead 回避）。台帳の昇格/降格は累積証拠に基づき、単一イベントで即断しない
