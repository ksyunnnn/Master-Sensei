# ADR-009: データ保存先の責務分離の徹底

Status: accepted
Date: 2026-03-28
Supersedes: ADR-005（market_observations廃止）

## Context

ADR-001で「Parquet=追記専用の生データ、DuckDB=更新ありの判断・知見」というハイブリッド戦略を採用した。

しかしADR-005で追加した`market_observations`テーブルに、`/update-regime`スキルがyfinanceから取得した生データ（VIX, VIX3M, Brent, DXY）を記録するようになり、以下の問題が発生:

1. **生データの保存先が二重化**: Parquet（FRED/Tiingo）とDuckDB（yfinance）に分散
2. **ADR-001の原則違反**: 「追記専用=Parquet」の基準に反し、生データがDuckDBに入っている
3. **振り返り不能**: `regime_assessments`の判定に使った入力値が構造化データとして記録されない。reasoningテキストの中にしか値が残らず、「VIXが25〜30の時のレジーム判定精度」のような分析ができない
4. **FREDデータ改訂の不可視**: FREDは公開後にデータを改訂するが、Parquetの上書き時にソース情報が記録されず、改訂の発生自体を検知できない

## Options

### A: Parquetへの生データ一本化 + regime_assessmentsスナップショット + Parquet source追跡

| 長所 | 短所 |
|------|------|
| ADR-001の原則を完全に回復 | regime_assessmentsのカラム数が10→16に増加 |
| 判断と入力値が1レコードで自己完結 | Parquetスキーマにsource/updated_at列を追加 |
| 改訂の検出がスナップショット比較で可能 | market_observationsの「手動補完」機能が失われる |
| assess_regime.pyのマージ処理が不要になり簡素化 | — |

### B: market_observationsをParquetに移行

| 長所 | 短所 |
|------|------|
| 全生データがParquetに統一 | status更新（unverified→verified）ができなくなる |
| ADR-001の原則に忠実 | レジーム判定に使った値の特定が別途必要 |

### C: 現状維持（原則を再定義）

| 長所 | 短所 |
|------|------|
| 実装変更不要 | ADR-001の原則と実態が乖離したまま |
| | 「生データはどこ？」に答えられない |

## Decision

> **Option Aを採用する。以下の4点を実施する。**
>
> 1. **生データの保存先をParquetに一本化する。** yfinance生データをProviderChain（ADR-006）経由で`update_data.py`のParquetパイプラインに統合する。
> 2. **Parquetにsource・updated_at列を追加する。** 各行がどのプロバイダから取得され、いつ更新されたかを行レベルで追跡する。
> 3. **`regime_assessments`に判定時の生入力値6カラムを追加する。** vix_value, vix3m_value, hy_spread_value, yield_curve_value, oil_value, usd_value（すべてDOUBLE）。判定に使った値のスナップショットを埋め込む。
> 4. **`market_observations`テーブルを廃止する。** ADR-005をsupersedeする。

## Rationale

### 判定行へのスナップショット埋め込み

複数の分野が「判定記録に入力値を埋め込む」パターンを推奨している:

- **Verraes (Decision Tracking, 2019)**: 入力データが改訂されうる場合、判定時点の値をスナップショットとして保存すべき。FREDはデータを改訂するため、JOINによる事後復元は「過去について嘘をつく」リスクがある
- **Kimball (Periodic Snapshot Fact Table)**: 日次スナップショットファクトテーブルでは、計測値をインライン・非正規化で格納する。`regime_assessments`はこのパターンに該当
- **SOX監査/SREアラート**: 判定記録は自己完結すべき。ソースシステムが変更・廃止された後も独立して解釈可能であること

### 生入力値の保存（計算値ではなく）

保存するのはVIX, VIX3M等の**観測された生値**であり、VIX/VIX3M比率のような計算値ではない:

- 生値から比率は再導出可能だが、逆はできない（ADR-003: 再導出可能な値は永続化しない）
- Kimballの原則では観測された粒度で保存する
- 将来VIX3Mの絶対水準を分析する可能性を残す

### カラム数の許容性

`regime_assessments`は10→16カラム。ADR-003の監視閾値（15カラムでEAV分解を検討）を超えるが、ハード閾値（20カラムで要見直し）以内。指標が6つで安定しており、EAV形式はクエリの複雑さ（self-JOIN必須）に見合わない。

### Parquet source列の必要性

FREDのデータ改訂は仮説ではなく確実に起きる事象。source+updated_at列により:

- 各行の出所と更新日時が明示される（Charter 3.1: 事実と推測の分離）
- 改訂の検出はregime_assessmentsスナップショット vs Parquet現在値の比較で可能（追加コストゼロ）
- 改訂**履歴**の保持は不要と判断。同一日付に複数行が必要になりデータモデルへの影響が大きく、スナップショット比較で代替可能（Charter 3.5: 最小限の複雑さ）

### market_observations廃止の妥当性

- ADR-005の「FRED遅延時の速報補完」は、yfinanceがParquetパイプラインに入ることで解消
- `verify_observation()`はテスト以外で一度も使用されていない
- 手動投入（Web検索値の記録）の実績もない
- API全障害時はParquetの前日データを使用し、reasoningに明記することで対応（Charter 3.5: 稀なケースのために仕組みを残さない）

### 既知の制約

- **同日再判定の上書き**: `save_regime()`は同一日付をDELETE→INSERTで処理するため、1日に2回判定すると1回目のスナップショットが消える。現状1日1回の運用で問題ないが、Decision Tracking原則の完全適用には別途対応が必要（本ADRのスコープ外）

## Consequences

### 実装タスク

- [ ] Parquetスキーマにsource（VARCHAR）・updated_at（TIMESTAMP）列を追加（cache_manager.py）
- [ ] `update_data.py`のマクロ取得部分をProviderChain方式に変更
- [ ] `regime_assessments`スキーマに入力値6カラムを追加（db.py）
- [ ] `save_regime()`メソッドのシグネチャに入力値パラメータを追加
- [ ] `market_observations`テーブル・関連メソッド（add_observation, get_latest_observations, get_observations_for_date, verify_observation）の廃止
- [ ] `assess_regime.py`のParquet/market_observationsマージ処理を削除し、Parquetのみ読み取りに簡素化
- [ ] `/update-regime`スキル定義の更新（yfinance直接取得 → Parquet読み取り + regime_assessmentsスナップショット記録）
- [ ] テスト更新（TestMarketObservations削除、regime snapshot/source列のテスト追加）

### 関連ドキュメント更新

- [ ] ADR-005のStatusを`superseded by ADR-009`に変更
- [ ] ADR-006 Consequencesの「market_observationsにsource記録」→「Parquet source列 + regime_assessmentsスナップショットで代替」に更新
- [ ] ADR-001のConsequencesに本ADRへの参照を追記
- [ ] ADR-003の監視ポイント「regime_assessmentsのカラム数: 9」→「16」に更新
- [ ] CLAUDE.mdのWrite基準テーブルからmarket_observationsを削除
- [ ] market_observations既存データの確認・アーカイブ

### 見直しトリガー

- regime_assessmentsのカラム数が20を超えた場合 → EAV形式`(date, indicator, value)`への分解を検討（ADR-003基準）
- Parquet source列でyfinance/FRED以外のプロバイダが増えた場合 → source管理の見直し
- 同日再判定の必要性が生じた場合 → regime_assessmentsのPK見直し（別ADR）
