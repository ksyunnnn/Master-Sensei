# ADR-024: regime_assessments の同日複数スナップショット許容

Status: proposed
Date: 2026-05-21

## Context

ADR-009 で `regime_assessments` テーブルに「判定時の生入力値スナップショット (6カラム)」を埋め込む設計を採用した。これにより「VIXが25〜30の時のレジーム判定精度」のような後検証が可能になった。

しかし運用を進める中で、以下の問題が顕在化した:

**問題1: 同日複数の判定が記録できない (上書き発生)**

現在の `save_regime()` 実装は `DELETE FROM regime_assessments WHERE date = ?` → `INSERT` の upsert 動作。同日内に複数回 `/update-regime` を実行すると、最後の値以外は失われる。

**問題2: 日中のレジーム遷移が観測できない**

2026-05-21 の実例:
- 08:11 JST 保存: `risk_on (score 0.71)` (5/20 close ベース、VIX 17.44 / Brent $105.40 / VIX_TERM steep_contango)
- 20:30 JST 再判定: `neutral (score 0.50)` (5/21 リアルタイム値、VIX 17.84 / Brent $107.09 / VIX_TERM 通常コンタンゴへ後退)

朝→夕で **risk_on → neutral のレジーム遷移** が発生したが、現状の upsert 仕様では朝のスナップショットを上書きするため、DB 上ではこの遷移が記録されない。

**問題3: ADR-009 の精神との不整合**

ADR-009 は「振り返り不能」を解消するため入力値スナップショットを必須化した。しかし同日内の複数判定が消える設計では「いつレジームが転換したか」「日中の市場動揺が判定にどう影響したか」を後検証できず、結果として ADR-009 の動機が部分的に未達成。

**問題4: イベント因果検証の精度低下**

`/review-events` で「あるイベントの3日後 review」を行う際、当日のレジーム遷移が記録されていないと「イベント発火時のレジーム」と「イベント結果確定時のレジーム」を分離できない。同日内で複数の重要 catalyst (例: FOMC議事録 + NVDA earnings) が発火する日には、特に精度が低下する。

## Research

### 既存設計の確認

`src/db.py`:
```python
def save_regime(self, dt: date, ...):
    self.conn.execute("DELETE FROM regime_assessments WHERE date = ?", [dt])
    self.conn.execute("INSERT INTO regime_assessments (date, ...) VALUES (?, ...)", [...])
```

`date` カラムが primary key 相当の制約として機能。

### 時系列スナップショットの一般的設計パターン

- **append-only ledger pattern**: イミュータブルな履歴テーブルを保持、最新値は ORDER BY + LIMIT 1 で取得
- **bi-temporal pattern**: valid_time と recorded_time を分離管理 (会計・規制業界で一般的)
- **slowly changing dimension type 2**: 各 record に valid_from / valid_to を持たせる

Master Sensei の用途では bi-temporal や SCD2 は過剰、シンプルな append-only ledger が適切。

### 既存類似テーブル

- `predictions`: id (auto-increment) PK、append-only、created_at で時系列保持。outcome 列で resolve 反映
- `events`: id (auto-increment) PK、append-only
- `knowledge`: id (auto-increment) PK、validated_at で再検証時刻保持

`predictions`/`events`/`knowledge` は既に append-only パターン。`regime_assessments` だけが upsert で例外的。

## Options

### A: id PK 化 + assessed_at カラム追加 (一体化案)

既存テーブルの schema を変更:
- `id` を auto-increment PK に変更
- `assessed_at` (TIMESTAMP WITH TIME ZONE) カラム追加
- `date` は維持 (日次集約用、`assessed_at::DATE` で導出可能だが UI/SQL 簡便化のため保持)
- 同日複数 record 許容

| 長所 | 短所 |
|------|------|
| 完全な append-only 化、ADR-009 精神に合致 | get_latest_regime, get_regime_by_date 等の SELECT 系を全部改修必要 |
| 1テーブルで完結、データ統合性高い | 既存クエリ (`WHERE date = ?` で1行想定) が破綻 |
| `predictions`/`events` と一貫した設計 | 移行コスト中 (既存17 record に assessed_at = date 12:00 JST 補完) |

### B: 履歴テーブル分離 (`regime_history` 新設)

- 既存 `regime_assessments` は最新値のみ (現状動作維持、upsert 継続)
- 新規 `regime_history` を作成、`save_regime()` 内で append-only に書く
- 読み側: 既存ユースケースは `regime_assessments` のまま、履歴検索のみ `regime_history` 使用

| 長所 | 短所 |
|------|------|
| 既存コードへの影響が最小 (SELECT 系は全部そのまま動く) | テーブル2つに分割、同期リスク (save_regime で両方書く必要) |
| 段階的移行可能、リスク低い | 「最新値」と「履歴」の整合性責任が save_regime に集中 |
| `predictions` の `outcome` カラムパターンと類似発想 | スキーマ重複 (両テーブルに同じカラム) |

### C: 現状維持 (上書き継続) + 運用注意

- ADR-003 「データ未更新で前日と同一」ならスキップに加え、「同日2回目の評価は記録しない」運用を明文化
- 同日内の重要遷移は condition.md の文章で記録

| 長所 | 短所 |
|------|------|
| 実装変更ゼロ | ADR-009 の精神と乖離継続 |
| | 同日遷移の振り返り不能、`/review-events` 精度低下継続 |

### D: (date, slot) 複合 PK

- slot enum (`'eod'`, `'intraday'`, `'pre-open'` など) を追加
- 同日複数 record を slot 単位で許容

| 長所 | 短所 |
|------|------|
| 構造化された slot 概念で意図明示 | slot 判定ロジックが複雑、自動化困難 |
| | 1日3-4スナップショットの上限を強制 (intraday 高頻度には対応不可) |

## Decision

> **Option B (履歴テーブル分離) を採用する。** 以下を実施する:
>
> 1. **新規テーブル `regime_history` を作成する。** schema は `regime_assessments` と同じカラムに加え、`id INTEGER PRIMARY KEY` (auto-increment) と `assessed_at TIMESTAMP WITH TIME ZONE NOT NULL` を持つ。append-only (DELETE/UPDATE は禁止)。
>
> 2. **`save_regime()` を改修する。**
>    - 既存の `regime_assessments` への DELETE→INSERT (最新値保持) は維持
>    - 同時に `regime_history` にも INSERT する (assessed_at = `now_jst()`)
>
> 3. **既存データの移行スクリプトを作成する。** `regime_assessments` の全 record (17件、2026-03 以降) を `regime_history` に `assessed_at = date + 12:00 JST` で補完移行する。
>
> 4. **新規メソッド `get_regime_history(date_range)` を追加する。** 期間内の全スナップショットを `assessed_at ASC` で返す。`/review-events` から呼び出し可能にする。
>
> 5. **既存の get メソッドは無変更。** `get_latest_regime()`, `get_regime_by_date()` などは `regime_assessments` を引き続き参照。

## Why Option B

- **Option A** が理論的には最も綺麗だが、SenseiDB の全 get メソッド改修が必要で、誤って既存挙動を壊すリスクが大きい。特に `/update-regime` `/scan-market` `/review-events` が依存しており、今夜の予測 ID 6 deadline (5/22 05:00 JST) 前後で破壊を起こすと観測ロスが大きい
- **Option B** は段階的・低リスク。既存 SELECT 系は1行も変えず、save_regime のみ拡張。同期リスクは save_regime 内に集中するため単体テストで担保可能
- **Option C** は ADR-009 の精神と乖離するため不採用
- **Option D** は slot enum の自動判定が困難 (実装側の負担増)

## Charter Impact

- Charter 5.x「自己評価メカニズム」: `/review-events` の評価精度向上が期待される (イベント発火時 vs 結果確定時のレジーム分離可能)
- ADR-009 との関係: ADR-009 の「振り返り不能」解消の動機を **同日内遷移にも拡張**する追補位置付け

## Consequences

### 反映先

- `src/db.py`:
  - `regime_history` テーブル定義追加
  - `save_regime()` に `regime_history` への INSERT 追加
  - `get_regime_history(start_date, end_date)` メソッド追加
- マイグレーションスクリプト: `scripts/migrate_024_regime_history.py` (既存 record の補完移行)
- テスト: `test_db_regime_history.py` (append-only 動作確認、同期検証)
- skill `/update-regime`: コード変更不要 (save_regime の呼び出し API は変わらない)
- skill `/review-events`: `get_regime_history` を活用するよう改善 (別タスク)

### トレードオフ

- ストレージ増加: 1日複数 record で履歴増加、ただし1 record < 1KB なので年間 365 record でも数十 MB 程度
- save_regime の I/O 倍増 (2 INSERT)、ただし無視できる範囲
- スキーマ重複: 同じカラム定義が2テーブルに存在、変更時の同期注意

### 見直しトリガー

- `regime_history` の record 数が 1日 100件超になった場合 (高頻度判定運用時) → スキーマ最適化検討
- ADR-009 の他のテーブル (predictions, knowledge) でも同様の同日複数 record 需要が顕在化した場合 → 全体的な append-only 戦略の再検討

### 実装タイミング

- 設計確定: 本 ADR で 2026-05-21
- 実装: 次セッション (5/22 以降、米寄付直前を避ける時間帯)
- 既存予測 ID 6 (deadline 5/22 05:00 JST) の解決後に実施推奨
