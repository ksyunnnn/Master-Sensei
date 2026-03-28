# ADR-011: GDR-001 Phase 1 スキーマ変更

Status: accepted
Date: 2026-03-29

## Context

GDR-001（成長計測体系の設計）Phase 1で以下のスキーマ変更が必要になった。

1. `knowledge.source_prediction_id` — 予測→結果→知見のKolbサイクル連鎖を追跡
2. `predictions.root_cause_category` — 予測失敗時の根本原因分類（同じ失敗の繰り返し検出）

加えて、3つの算出関数をdb.pyに追加した:
- `get_brier_decomposition()` — Murphy (1973) Brier Score 3成分分解
- `get_baseline_score()` — 50%無情報ベースラインとの比較
- `get_kolb_cycle_rate()` — サイクル完遂率

GDR-001は成長メカニズムの判断記録であり、ソフトウェア構造の判断（スキーマ変更）はADRの管轄（CLAUDE.md Rules）。本ADRでスキーマ変更の根拠と影響を記録する。

## Options

### カラム追加

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A: 既存テーブルにカラム追加 | 最小変更。主キー不変 | 既存行のNULL率が上がる | **採用** |
| B: 新テーブル（prediction_analyses等） | 正規化。NULL回避 | テーブル数増加（ADR-003の10テーブル閾値に接近） | 不採用 |

選択肢Aの根拠: ADR-003 §4「既存テーブルへのカラム追加で済む条件」に合致。
- 主キーが変わらない
- 同一エンティティの属性（予測の根本原因、知見の出典予測）
- NULL率は一時的に高い（既存14知見中2件のみ紐付け、既存1予測中1件のみ分類）が、データ蓄積に伴い改善する

### 算出関数

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A: db.pyにメソッド追加（永続化しない） | ADR-003原則「再導出できる値は永続化しない」に準拠 | N/A | **採用** |
| B: 結果をテーブルに永続化 | キャッシュ効果 | Decision Tracking原則に反する（ロジック変更時に過去の値が不正確に） | 不採用 |

## Decision

> 1. `knowledge`テーブルに`source_prediction_id INTEGER`カラムを追加する
> 2. `predictions`テーブルに`root_cause_category VARCHAR`カラムを追加する
> 3. Brier 3成分分解・Baseline Score・Kolbサイクル率は都度算出し、永続化しない

### root_cause_categoryの値域

| 値 | 意味 | 例 |
|----|------|-----|
| overconfidence | 確信度が高すぎた | 予測#1: 構造的risk_offでVIX低下を45%と評価 |
| underconfidence | 確信度が低すぎた | 起きたのに低く見積もった |
| wrong_direction | 方向自体が間違い | bullish予測がbearish結果 |
| timing | 方向は正しいが期限内に到達せず | |
| black_swan | 予見不能な外部ショック | |
| stale_info | 古い情報に基づく判断 | |

値は自由テキスト（VARCHAR）。上記は推奨値であり、新カテゴリの追加は自由。N≧30蓄積後にENUM化を検討する。

## Rationale

- GDR-001 Research §領域横断の共通原則「サイクルを閉じる」「分解してから統合する」の実装
- ADR-003 Decision Tracking Principle: 判断時点の根拠（root_cause）を永続化
- ADR-003 §永続化しないもの: 集計値は都度計算で対応（Brier分解、Baseline、Kolb率）

## Consequences

- [x] `_init_schema()`にカラム追加済み
- [x] 既存DBマイグレーション済み（ALTER TABLE）
- [x] テスト8件追加（99テスト全パス）
- [ ] ADR-003 §現スキーマへの適用テーブルを更新 → 本ADR作成後に実施
- [ ] ADR-003 §永続化しないものに3関数を追記 → 本ADR作成後に実施

### NULL率の監視

| カラム | 現在のNULL率 | 許容理由 | 見直しトリガー |
|--------|------------|---------|--------------|
| knowledge.source_prediction_id | 86%（14件中12件NULL） | 既存知見の大半は予測起因ではない。今後の予測→知見連鎖で改善 | 50%を下回らない状態が3ヶ月続いたら子テーブル分離を検討 |
| predictions.root_cause_category | 50%（2件中1件NULL） | 未解決予測はNULL。解決時に記録 | N≧10で未記入率が30%超なら運用を見直す |
