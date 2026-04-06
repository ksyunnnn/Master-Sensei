---
name: sensei-journal
description: Master Senseiの市場日誌。直近のイベント・レジーム・知見・予測を元に、新聞連載風のナラティブをdocs/journal/に執筆する
---

Master Senseiの日誌を執筆してください。

## コンセプト

新聞連載のような市場ナラティブ。データの羅列ではなく、**なぜ今この状況なのか**をストーリーとして語る。各回は前回からの続きで、読者（=ユーザー）が連載を追うように市場の流れを理解できる。

## タイムゾーン

まず現在時刻を確認する: `TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M JST'`

## 手順

### 1. 素材収集（1スクリプトで実行）

```bash
python << 'PYEOF'
import duckdb
from src.db import SenseiDB, now_jst, today_jst

conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)

# レジーム
regime = db.get_latest_regime()
print(f"=== レジーム: {regime['overall']} ({regime['date']}) ===")
print(f"  reasoning: {regime['reasoning']}")

# 直近イベント（48h以内 + 今後の予定イベント）
events = db.get_active_events()
print(f"\n=== 直近イベント（最新15件） ===")
for e in events[:15]:
    print(f"  [{e['category']}] {e['event_timestamp']} | {e['impact']} | {e['summary'][:80]}")

# 未解決予測
preds = conn.execute(
    "SELECT * FROM predictions WHERE outcome IS NULL ORDER BY deadline"
).fetchdf().to_dict('records')
print(f"\n=== 未解決予測 ({len(preds)}件) ===")
for p in preds:
    print(f"  #{p['id']} {p['subject'][:50]} | {p['confidence']*100:.0f}% | 期限{p['deadline']}")

# 最新知見（直近検証5件）
knowledge = db.get_active_knowledge()
recent_k = sorted(knowledge, key=lambda k: k.get('last_verified_date') or k['discovered_date'], reverse=True)[:5]
print(f"\n=== 最新知見（上位5件） ===")
for k in recent_k:
    tldr = k.get('tldr') or k['content'][:60]
    print(f"  {k['id']}: {tldr} [{k['verification_status']}]")

# トレード
trades = conn.execute(
    "SELECT * FROM trades ORDER BY entry_date DESC LIMIT 3"
).fetchdf().to_dict('records')
if trades:
    print(f"\n=== 直近トレード ===")
    for t in trades:
        print(f"  #{t['id']} {t['instrument']} {t['direction']} | pnl={t.get('pnl_pct', 'open')}")

conn.close()
PYEOF
```

### 2. 前回の日誌を読む

```bash
ls -1 docs/journal/ | sort | tail -1
```

前回ファイルがあれば Read で読み、「前回のあらすじ」を把握する。初回なら「創刊号」として書く。

### 3. 日誌を執筆

以下の構成で `docs/journal/YYYY-MM-DD.md` を作成する。

```markdown
# Sensei's Journal — Episode N: [サブタイトル]

*YYYY-MM-DD HH:MM JST*

---

> **前回のあらすじ** — [前回の核心を1-2文で。初回は省略]

---

## Scene 1: [見出し]

[ナラティブ。データを織り込みながらストーリーを展開]

## Scene 2: [見出し]

...

## Scene N: [見出し]

...

---

## 本日のポジション観点

| 銘柄 | 方向 | 根拠 | リスク |
|------|------|------|--------|
| ... | ... | ... | ... |

## 次回予告

[今後24-72hの注目イベント・判断ポイントを1-3文で予告]

---

*レジーム: [overall] | VIX: [値] | Brent: $[値] | 保有: [あり/なし]*
```

### 4. 会話にも表示

Writeで書いた内容を、会話にもそのまま表示する。ユーザーは「読む」体験を楽しむ。

## 執筆ガイドライン

### 文体
- 一人称は使わない。三人称の観察者視点（「市場は〜」「Trumpは〜」）
- データは文中に自然に織り込む（表にしない。表はポジション観点のみ）
- K-XXX知見は名前を出さずに原則として活用（例: 「過去36日間で確立されたパターンが再び作動した」）
- 確定事実と推測を明確に分離。推測は「〜かもしれない」「〜の可能性がある」

### Scene構成
- 1 Scene = 1テーマ（地政学、マクロ、セクター等を混ぜない）
- 時系列で展開するのが基本だが、テーマの重要度で並べ替えてもよい
- 各Sceneは独立して読めるが、全体で1つの物語になる
- 3-5 Scene が適切（多すぎない）

### 連載としての一貫性
- 前回からの伏線回収を意識する（「先週の48時間は結局〜」）
- 登場人物（Trump, Powell, Dimon等）に一貫した描写
- 繰り返されるパターンには名前をつける（「Hormuzサイクル」「脅迫-撤回ダンス」等）
- 予告で張った伏線は次回で回収する

### やらないこと
- データの羅列（scan-marketの仕事）
- 投資助言（「買うべき」「売るべき」は書かない）
- 感情的な煽り（「暴落！」「爆上げ！」）
- 架空の情報や推測を事実のように書くこと

## 注意事項

- SQLは直接書かず、SenseiDBのメソッドを使用する（ADR-008）
- ファイル名は `docs/journal/YYYY-MM-DD.md`（1日1ファイル）
- 同日2回目の実行は上書き（日付が同じなら同一ファイル）
- エピソード番号は `docs/journal/` 内のファイル数 + 1 で自動採番
