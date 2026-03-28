# ADR-003: データガバナンス（Read/Write基準・スキーマ変更基準）

Status: accepted
Date: 2026-03-26

## Context

Master SenseiのDuckDB（sensei.duckdb）に何を書き込み、何を書き込まないかの基準が未定義。
基準がないと過少記録（DBが空のまま）または過剰記録（ノイズだらけ）のどちらかに陥る。
テーブル追加・スキーマ変更の判断基準も必要。

参考文献:
- Verraes: Eventsourcing Patterns — Decision Tracking (2019)
- Fowler/Sadalage: Evolutionary Database Design (2016)
- Fontaine: Database Modelization Anti-Patterns (2018)
- Metaculus (github.com/Metaculus/metaculus): 予測プラットフォームのスキーマ設計

## 1. Write基準（何をDBに永続化するか）

### 原則: Decision Tracking Principle

> 判断ロジックが将来変わりうるなら、判断時点の値と根拠を永続化する。
> 入力データから再導出できる値は永続化しない。

（Verraes 2019: "If we recalculate decisions using updated logic, we get a different outcome. The system is lying about the past."）

### テーブル別Write基準

#### predictions — 予測記録

| 条件 | Write? | 理由 |
|------|--------|------|
| 対象・期限・確信度・根拠・反証条件がすべて埋まる | Yes | Brier score計測に必要な最小セット |
| 確信度が付与できない漠然とした見通し | **No** | 検証不能。会話で述べるだけ |
| 期限がない（「いつか起きる」） | **No** | 検証不能 |
| 確信度 < 0.1 or > 0.9 の極端な予測 | Yes（ただし注記） | 過信/過小評価の検出に有用 |

**Write前チェックリスト:**
1. 対象が具体的か（「VIXが30を超える」はOK、「市場が荒れる」はNG）
2. 期限があるか（日付指定）
3. 結果が二値判定可能か（Yes/No）
4. 根拠を1文以上書けるか

#### knowledge — 知見DB

| 条件 | Write? | 理由 |
|------|--------|------|
| データまたは複数回の観察に基づく発見 | Yes | 蓄積すべき |
| 教科書的な一般論（「VIXは恐怖指数」） | **No** | 誰でも知っている。付加価値なし |
| 1回の観察だけに基づく仮説 | Yes（status=hypothesis） | ただし検証前であることを明示 |
| 反証された知見 | **削除しない** | invalidation_reasonを記録して残す |

**Write前チェックリスト:**
1. 「これを知らなかった過去の自分が判断を誤る」と言えるか
2. 根拠（evidence）を具体的に書けるか
3. 既存の知見と重複していないか（既存があればupsert）

#### events — イベント記録

| 条件 | Write? | 理由 |
|------|--------|------|
| 対象シンボルの価格に影響しうるイベント | Yes | レジーム判定の入力 |
| 対象スコープ外（個別株、仮想通貨等） | **No** | スコープ外 |
| 既に類似イベントが記録済み | **No**（dedup） | timestamp+category+summaryで重複判定 |

#### regime_assessments — レジーム判定

| 条件 | Write? | 理由 |
|------|--------|------|
| マクロデータ更新後のレジーム判定 | Yes | 日次で記録。入力値スナップショット（6指標の生値）必須（ADR-009） |
| データ未更新で前日と同じ | **No** | 冗長。前日の記録を参照すればよい |
| 判定ロジック変更後の再判定 | Yes（新レコード） | 旧判定は上書きしない（Decision Tracking） |

### 永続化しないもの

| データ | 理由 | 代替 |
|--------|------|------|
| Brier score（集計値） | predictions テーブルから再計算可能 | `get_brier_score()` で都度算出 |
| calibration curve | 同上 | `get_calibration_data()` で都度算出 |
| API応答の生キャッシュ | Parquetに保存済み | cache_manager経由で参照 |
| セッション中の探索的分析 | 一時的。結論だけ knowledge に書く | 会話コンテキストで保持 |
| サマリーレポート | 入力データから再生成可能 | 都度生成 |

## 2. Read基準（いつ何を読むか）

### セッション開始時に読むもの

| データ | クエリ | 理由 |
|--------|--------|------|
| 最新レジーム判定 | `SELECT * FROM regime_assessments ORDER BY date DESC LIMIT 1` | 現在の市場文脈 |
| 未解決の予測 | `SELECT * FROM predictions WHERE outcome IS NULL ORDER BY deadline LIMIT 10` | 期限切れチェック |
| 最近の知見（上位5件） | `SELECT * FROM knowledge WHERE verification_status != 'invalidated' ORDER BY last_verified_date DESC LIMIT 5` | 直近の学び |

### テーブル全体を読まない

全件ロードはコンテキストを浪費する。必要なデータだけクエリする。

## 3. スキーマ変更の判断基準

### 変更が正当化される条件（Fowler/Sadalage Evolutionary DB Design）

| シグナル | 閾値 | アクション |
|---------|------|----------|
| カラムのNULL率 | > 50%の行がNULL | そのカラムは別テーブルに属する可能性 |
| カラム数 | > 20カラム | テーブルが複数の関心事を表現している |
| VARCHAR型に構造化データ | 日付・数値・JSONが文字列に入っている | 適切な型に変更 |
| クエリでCASE WHENが頻出 | カラムの意味が曖昧 | カラム分割またはENUM化 |
| 同じデータが複数テーブルに存在 | — | 正規化または参照テーブル抽出 |

### 変更のプロセス

1. シグナルを検出（上記の閾値チェック）
2. ADRに変更理由と選択肢を記録
3. マイグレーションコードを `_init_schema()` または専用関数に実装
4. テストを書いてから適用
5. 旧スキーマからのマイグレーションパスを確保（db.py起動時に自動判定）

## 4. テーブル追加の判断基準

### 新テーブルが必要な条件

| シグナル | 理由 |
|---------|------|
| 既存テーブルと**異なる主キー**を持つ | 別エンティティ |
| 既存テーブルに対して**1:N関係** | 正規化 |
| 既存テーブルと**異なるライフサイクル**（作成・更新タイミングが違う） | 関心の分離 |
| 追加カラムが既存行の50%以上でNULLになる | スパースデータ → 子テーブルに分離 |

### 既存テーブルへのカラム追加で済む条件

| シグナル | 理由 |
|---------|------|
| 全既存行に適用され、同じライフサイクル | 同一エンティティの属性 |
| 主キーが変わらない | 同一エンティティ |

### 現スキーマへの適用

| 監視ポイント | 現状 | トリガー |
|-------------|------|---------|
| regime_assessments のカラム数 | 16（date + 6 regime + 6 input values + overall + reasoning + created_at）（ADR-009） | カラム数が20を超えたら (date, indicator, value) 形式への分解を検討 |
| knowledge.confidence がVARCHAR | 'low'/'medium'/'high' の3値 | 分析クエリで数値化が頻繁に必要になったらDOUBLEに変更 |
| predictions.brier_score の冗長性 | confidence + outcome から再計算可能 | 単一ユーザーシステムでは許容。パフォーマンス問題が出たら削除 |

## 5. ガバナンスのレビュートリガー

以下のいずれかに該当したとき、このADRを見直す:

- テーブル数が10を超えた
- 1テーブルのカラム数が20を超えた
- NULL率50%超のカラムが存在する
- 新しいデータ種別の永続化要求が発生した
- 月次レビュー（Charter Section 7.3）のタイミング

## Consequences

- CLAUDE.mdにWrite基準のサマリーを追記
- 各テーブルへのWriteはチェックリストを満たす場合のみ実行
- スキーマ変更は必ずADRに記録してから実施
- 月次レビューでNULL率・カラム数をチェック
