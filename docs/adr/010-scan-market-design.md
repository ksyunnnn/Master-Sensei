# ADR-010: ニュース収集・イベント管理の設計

Status: accepted
Date: 2026-03-29

## Context

Master SenseiはレバレッジETF（SOXL/TQQQ/TECL/SPXL等）の短期トレードを支援するシステムである。市場に影響するニュース・イベントの収集と記録が必要だが、体系的な収集ワークフローが存在しなかった。

先行するfeasibility_study（`../feasibility_study/macro/`）では、`/macro`という単一スキルでニュース収集からレジーム判定まで一気通貫で行う設計だった。これをmaster_senseiに移植するにあたり、既存のスキル体系（ADR-008で確立した責務分担）との整合性を検討した。

### 解決すべき課題

1. **ニュース収集の仕組みがない**: ADR-002でTiingo News APIを見送って以降、Claude CodeのWebSearchを使った収集ワークフローが未設計
2. **イベントの登録経路が不明**: `events`テーブルに手動登録とスキル経由の登録が混在するが、区別できない
3. **スキル実行履歴がない**: `/scan-market`を前回いつ実行したかがわからず、調査対象期間を決定できない
4. **イベントの事後検証がない**: `event_reviews`テーブルは存在するが、検証ワークフロー（スキル）がない

## Decision

### 1. スキルの責務分離（4スキル体制）

> feasibility_studyの`/macro`（1スキルで全部やる）ではなく、責務ごとにスキルを分離する。

| スキル | 責務 | 入力 | 出力 |
|--------|------|------|------|
| `/scan-market` | WebSearchでニュース収集 → `events`テーブルに登録 | WebSearch結果 | eventsレコード |
| `/update-regime` | Parquetからマクロデータ読み取り → レジーム判定 → `regime_assessments`に記録 | Parquetキャッシュ | regime_assessmentsレコード |
| `/review-events` | 3日以上経過した未検証イベントのimpact事後検証 → `event_reviews`に記録 | events + WebSearch | event_reviewsレコード |
| `/verify-knowledge` | 180日以上未検証の知見を検証 → 検証日更新 | knowledge | knowledgeレコード更新 |

理由: ADR-008で確立した「Hook=自動/Skill=ユーザー起点」の原則に従い、各スキルが単一責務を持つ。`/macro`のように1スキルに複数責務を持たせると、部分実行ができない（レジーム判定だけしたいのにニュース収集も走る等）。

### 2. `events.source`列の追加（登録経路の識別）

> `events`テーブルに`source VARCHAR DEFAULT 'manual'`列を追加する。

値の例:
- `'manual'`: 会話中にユーザーが口頭で伝え、Claude Codeが登録したイベント
- `'scan-market'`: `/scan-market`スキル経由で登録したイベント

理由: 監査ログ設計の標準（Red Gate, AWS Event Sourcing）では、各レコードに「誰が・何で作ったか」を記録するのが基本。手動とスキル経由を区別できないと、`/scan-market`の調査範囲決定やデータ品質分析ができない。

### 3. `skill_executions`テーブルの新設（スキル実行履歴）

> 全スキルの実行履歴を1テーブルで管理する。

```sql
CREATE TABLE skill_executions (
    id INTEGER PRIMARY KEY,
    skill_name VARCHAR NOT NULL,        -- 'scan-market', 'update-regime' 等
    executed_at TIMESTAMPTZ NOT NULL,    -- 実行完了時刻（JST timezone-aware）
    result_summary VARCHAR,             -- '6 events added' 等
    metadata VARCHAR,                   -- JSON: スキル固有のデータ
    created_at TIMESTAMP DEFAULT current_timestamp
)
```

`metadata`列（JSON文字列）にスキル固有の情報を格納する。例えば`/scan-market`では:
```json
{
    "latest_source_date": "2026-03-28T15:00:00+09:00",
    "categories_searched": ["geopolitical", "fed", "semiconductor", "oil", "tariff", "market"]
}
```

**なぜ`scan_history`ではなく汎用の`skill_executions`にしたか:**

Apache Airflowの`dag_run`テーブルを参考にした。Airflowは数百種類のDAG（ワークフロー）を1つの`dag_run`テーブルで管理し、`dag_id`列でジョブの種類を区別する。スキルごとに専用テーブルを作ると、スキル追加のたびにテーブルが増え、ADR-003のテーブル数閾値（10テーブルで見直し）に近づく。

### 4. `/scan-market`の品質基準（誤情報排除）

> 3層の検証体制でイベント登録の品質を担保する。

**層1 ソース品質管理:**
- Tier 1（政府・企業IR・国際機関の公式発表）: そのまま採用
- Tier 2（Reuters, AP, CNBC, CNN, NPR, Al Jazeera, BBC等のメジャーメディア）: 採用。ただし数値はTier 1で裏取り推奨
- Tier 3（個人ブログ・SNS・無名サイト）: **登録不可**

**層2 クロスリファレンス:**
- 定性イベント（戦争・政策等）: 2つ以上の独立したTier 1-2ソースで確認できたもののみ登録
- 定量データ（VIX・原油価格等）: `data/parquet/`のParquetキャッシュと照合可能な場合は照合。WebSearch値とParquet値が矛盾する場合は不採用

**層3 検証レベルの明示:**
- イベント登録時の`impact_reasoning`に検証レベルを含める（例: 「FRB公式声明で確認」「CNBC+NPRで報道」）
- 検証できなかった情報は登録しない

根拠: ジャーナリズムのファクトチェック方法論（Ballotpedia、DataJournalism.com）と金融データ検証のベストプラクティス（Investing.com）を調査し、Master Senseiの運用規模に適したレベルに簡素化した。

### 5. `/scan-market`の調査対象期間

> 通常は前回実行時刻〜現在の差分スキャン。初回のみ15ヶ月（2025年1月〜現在）の拡大スキャンを実施する。

通常運用:
- `skill_executions`テーブルから`WHERE skill_name = 'scan-market' ORDER BY executed_at DESC LIMIT 1`で前回実行時刻を取得
- 前回実行時刻以降のニュースを調査
- 前回記録がない場合は直近7日間をデフォルトとする

初回拡大スキャン（15ヶ月）の理由:
- トランプ政権の関税政策は2025年1月の就任直後から始まっており、IEEPA関税→最高裁違憲判決（2026年2月）→Section 122/232への切り替えという経緯がある。直近7日だけでは政策パターンの文脈が取れない
- 半導体セクターの季節性（CES 1月、決算シーズン1/4/7/10月）を把握するには最低1年のサイクルが必要
- ADR-003のWrite基準（対象シンボルの価格に影響しうるイベント）のみでフィルタし、「現在のレジームに関係するか」ではフィルタしない。Charter 4.3が警告する確証バイアス（現在のレジームを支持するイベントだけ拾う）を排除するため

初回スキャン時の追加ルール:
- 四半期×6カテゴリで検索クエリを分割し、検索エンジンの最新記事偏重を回避
- 検索クエリに必ず年月を含める（"January 2025"等）。2025/2026の年の取り違え防止
- 後日撤回・改訂された情報でないか確認

### 6. 調査報告のフォーマット

> 「調査対象期間」ではなく「取得できた最新情報」を報告する。

WebSearchの検索結果がいつの時点まで反映されているかは制御できない（検索エンジンのインデックス更新遅延）。「2026-03-28 21:30 JSTまで調査」と報告しても、実際には数時間前のニュースまでしかヒットしていない可能性がある。

Charter 3.1（事実と推測の分離）に基づき、検証可能な事実のみ報告する:
- 調査実施時刻（`datetime.now(tz=JST)`で正確に取得可能）
- 取得できた最新情報の日時とソース名（検索結果から確認可能）

## Rationale

### feasibility_studyからの教訓

feasibility_study（`../feasibility_study/macro/`）では以下が有効だった:
- WebSearch + Claude判断によるニュース収集は実用的
- `event_reviews`テーブルのlesson参照がimpact判定精度の改善に寄与
- 2段階設計（収集→注入）が安定動作

一方、以下を変更した:
- `/macro`の一気通貫 → 4スキル分離（ADR-008の責務分担原則）
- `summary.md`生成 → 不要（session_startフックが既に5項目を注入しており、イベント追加でコンテキスト膨張を避ける）
- `scan_history`専用テーブル → `skill_executions`汎用テーブル（Airflow dag_runパターン）

### タイムゾーン処理

Claude Code公式機能の `` !`command` `` 構文を使い、スキル実行時に現在のJST時刻を動的注入する。`src/db.py`の`JST`定数と`_require_aware()`ガードにより、naive datetimeの混入を防止する。

## Consequences

### 実装済み
- [x] `events.source`列追加（`src/db.py`、デフォルト値`'manual'`）
- [x] `skill_executions`テーブル新設（`src/db.py`）
- [x] `record_skill_execution()` / `get_last_skill_execution()`メソッド追加
- [x] `/scan-market`スキル作成（品質基準・JST動的注入・実行履歴記録）
- [x] `/review-events`スキル作成（3日経過後の事後検証ワークフロー）
- [x] テスト追加（91テスト全パス）
- [x] 既存DB（`data/sensei.duckdb`）のマイグレーション完了

### 運用サイクル
```
/scan-market → /update-regime → （数日後） → /review-events
  ニュース収集    レジーム判定         impact事後検証
```

### 見直しトリガー
- `events`テーブルが500件を超えた場合 → 読み出し時のフィルタ最適化を検討
- `/scan-market`の品質基準（Tier分類・クロスリファレンス）が実運用で過剰/不足と判明した場合
- 新しいスキルが`skill_executions`を使い始めた場合 → `metadata`のJSON構造を標準化するか検討
