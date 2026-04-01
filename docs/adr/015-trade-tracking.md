# ADR-015: トレード記録のデータ設計

Status: accepted
Date: 2026-04-01

## Context

SOXLトレード（28株@$42.949 → $47.24、+10%）を実施し、エントリー履歴を記録する場所がないことが判明。以下3つの関心を満たすデータ設計が必要：

1. **口座の事実** — いくら入金し、何を買い、何を売ったか（生データ）
2. **トレードの成績** — 1ラウンドトリップとしての損益、保有期間
3. **判断の記録** — どんな条件・根拠でエントリーし、何を学んだか

### 設計原則

- **生データ層と判断層の分離**（ADR-001の思想を拡張）
- **疎結合** — 判断層のスキーマ変更が生データに影響しない
- **Decision Tracking Principle**（ADR-003）— 判断時点の値をスナップショットとして保存

### ベンチマーク調査

| サービス | 特徴 | Master Senseiへの示唆 |
|---------|------|---------------------|
| Edgewonk | ファクト層+分析層+心理層の3層。規律スコア・チェックリスト遵守率 | setup_type, discipline_score の概念 |
| Tradervue | 自動インポート+多軸分析（時間帯別・銘柄別・サイズ別） | 分析クエリの設計指針 |
| Red Gate Trading Model | trade, current_inventory, offer の正規化モデル | 正規化の参考。ただし高頻度取引向け |
| Nik Stehr Risk Model | Book-Trade-Position の3層 + bi-temporal tracking | スナップショットの考え方 |

## Decision

### 2テーブル構成（生データ層 + 判断層）

#### 1. account_transactions（Parquet — 生データ層）

サクソバンクExportの事実をそのまま記録。判断層に一切依存しない。

```
data/parquet/account/transactions.parquet
```

| カラム | 型 | 説明 |
|--------|-----|------|
| trade_date | DATE | 取引日 |
| settlement_date | DATE | 受渡日 |
| type | VARCHAR | deposit / withdrawal / buy / sell |
| instrument | VARCHAR | 銘柄コード（nullable、入出金時はnull） |
| quantity | DOUBLE | 株数（nullable） |
| price_per_unit | DOUBLE | 約定単価（nullable） |
| amount | DOUBLE | 記帳額。売買はUSD、入出金はJPY（currencyカラムで区別） |
| currency | VARCHAR | 記帳額の通貨。USD / JPY |
| fx_rate | DOUBLE | JPY/USD換算レート（nullable。JPY建て取引時はnull） |
| amount_jpy | DOUBLE | 円換算額（nullable。currency=JPYならamountと同値。currency=USDならamount × fx_rate） |
| realized_pnl | DOUBLE | 実現損益（nullable、受渡後に確定） |
| broker_ref | VARCHAR | サクソバンク取引ID（nullable） |
| source | VARCHAR | 取り込み元（例: saxo_export_2026-04-01） |
| imported_at | TIMESTAMP | インポート日時 |

**amount / currency / fx_rate / amount_jpy の関係:**

| type | currency | amount | fx_rate | amount_jpy |
|------|----------|--------|---------|------------|
| deposit | JPY | 150000 | null | 150000 |
| buy | USD | -1202.57 | 149.5 | -179784 |
| sell | USD | 1322.72 | 149.5 | 197747 |

**Write基準:** サクソバンクからExcelエクスポート → インポートスクリプトで取り込み。手動入力は禁止（ソース不明のデータを生データ層に入れない）。

**更新パターン:** 受渡日に値が確定した場合、同一source のExcelを再インポートして全置換（既存のマクロParquetと同じ運用）。

#### 2. trades（DuckDB — 判断層）

1ラウンドトリップ = 1行。エントリー時の条件スナップショットと事後評価を含む。

| カラム | 型 | 説明 |
|--------|-----|------|
| id | INTEGER PK | 自動採番 |
| instrument | VARCHAR NOT NULL | 銘柄コード |
| direction | VARCHAR NOT NULL | long / short |
| entry_date | DATE NOT NULL | エントリー日 |
| entry_price | DOUBLE NOT NULL | エントリー価格 |
| exit_date | DATE | エグジット日（nullable、未決済時） |
| exit_price | DOUBLE | エグジット価格（nullable） |
| quantity | INTEGER NOT NULL | 株数 |
| pnl_usd | DOUBLE | 実現損益USD（nullable） |
| pnl_pct | DOUBLE | 損益率%（nullable） |
| commission_usd | DOUBLE | 手数料合計（nullable） |
| holding_days | INTEGER | 保有日数（nullable） |
| --- スナップショット --- | | |
| regime_at_entry | VARCHAR | エントリー時のレジーム（例: risk_off） |
| vix_at_entry | DOUBLE | エントリー時のVIX |
| brent_at_entry | DOUBLE | エントリー時のBrent |
| --- 判断記録 --- | | |
| confidence_at_entry | DOUBLE | エントリー時の確信度 0.0-1.0（Charter 3.2準拠） |
| setup_type | VARCHAR | 戦略タイプ（例: de_escalation_bounce） |
| entry_reasoning | TEXT | エントリー根拠 |
| exit_reasoning | TEXT | エグジット根拠（nullable） |
| --- 事後評価 --- | | |
| discipline_score | INTEGER | 規律スコア 1-5（nullable） |
| review_notes | TEXT | 事後レビュー（nullable） |
| prediction_id | INTEGER | 関連予測（nullable、ソフト参照） |
| created_at | TIMESTAMP | レコード作成日時 |

### NULL率の事前予測

未決済トレード時にnullableカラムがどの程度NULLになるかを予測する（ADR-003 Section 3）。

| 状態 | NULLカラム数 | NULL率 | 評価 |
|------|------------|--------|------|
| エントリー直後（未決済） | exit_date, exit_price, pnl_usd, pnl_pct, commission_usd, holding_days, exit_reasoning, discipline_score, review_notes (9/21) | 43% | 閾値50%未満。許容 |
| エグジット完了（レビュー前） | discipline_score, review_notes (2/21) | 10% | 良好 |
| レビュー完了 | 0/21 | 0% | 全カラム充填 |

未決済状態は一時的（数日〜数週間）であり、恒常的に50%を超えることはない。

### 疎結合の実現

| 設計判断 | 内容 |
|---------|------|
| account_transactions → trades | **参照なし**。両テーブルは独立 |
| trades → regime_assessments | **スナップショット**（regime_at_entry, vix_at_entry）。FKではなく値コピー |
| trades → predictions | **ソフト参照**（prediction_id、nullable）。FKは使わずINTEGER型のみ |
| trades の再構築 | account_transactions + 判断記録から復元可能（生データは不変） |

### ADR-003 Write基準の追加

#### account_transactions — 口座取引記録

| 条件 | Write? | 理由 |
|------|--------|------|
| サクソバンクExportに存在する取引 | Yes | 外部ソースの事実 |
| 手動で記憶から入力 | **No** | ソース不明。必ずExportから |

#### trades — トレード判断記録

| 条件 | Write? | 理由 |
|------|--------|------|
| エントリー・エグジットが完了したトレード | Yes | 判断の記録 |
| エントリー根拠・レジームスナップショットが埋まる | Yes | Decision Tracking |
| 未約定の検討段階 | **No** | 会話で保持。約定後に記録 |

### 永続化しないもの（ADR-003準拠）

| データ | 理由 | 代替 |
|--------|------|------|
| 口座残高 | account_transactionsから再計算可能 | `SUM(amount_jpy) FROM transactions` で都度算出 |
| 勝率・平均R:R | tradesから再計算可能 | クエリで都度算出 |
| エクイティカーブ | account_transactions + tradesから再計算可能 | クエリで都度算出 |
| ポジション一覧（現在保有） | 未決済tradesから導出可能 | `WHERE exit_date IS NULL` で都度算出 |

## Consequences

- `data/parquet/account/` ディレクトリを新設
- ADR-001のファイル配置セクションに `account/` を追記
- `src/db.py` の `_init_schema()` に trades テーブルを追加
- `SenseiDB` に `add_trade()`, `close_trade()`, `review_trade()` メソッドを追加
- サクソバンクExcelインポートスクリプトを作成（将来タスク）
- ADR-003のWrite基準セクションに上記2テーブルを追記
- SessionStartフックに「未決済トレードの有無」を表示（将来タスク）
- 見直しトリガー: 部分約定・ナンピン・段階利確が頻発した場合、executions 子テーブルの分離を検討
