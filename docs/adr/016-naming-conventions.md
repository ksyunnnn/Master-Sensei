# ADR-016: 命名規則

Status: accepted
Date: 2026-04-01

## Context

テーブル数が6→8に増加し（ADR-015 trades + account_transactions）、Parquetディレクトリも4つに拡大する。
命名規則が暗黙のままだと、新規追加時に不整合が生まれるリスクがある。

既存の慣習を棚卸しし、調査結果と照合して明文化する。

### 調査結果

| ソース | テーブル名 | カラム名 | FK名 | 根拠 |
|--------|----------|---------|------|------|
| Ovid (dev.to) | **複数形** + snake_case | snake_case | `{referenced_table}_id` | 予約語衝突回避、JOIN時のバグ発見容易性 |
| RootSoft (GitHub) | **単数形** + snake_case | snake_case | `{referenced_table}_id` | 複数形の曖昧さ回避（person→people?）、4GLとの整合 |
| PostgreSQL慣習 | 複数形が主流 | snake_case | `{table}_id` | コミュニティ標準 |
| DuckDB公式 | 明示的規則なし | case-insensitive | — | snake_case推奨（dlt docsより） |

**単数 vs 複数の結論:** 業界に正解はない。**一貫性が最重要**。

### 既存の慣習棚卸し

**DuckDBテーブル名（現状）:**

| テーブル | 単複 | snake_case |
|---------|------|-----------|
| events | 複数 ✓ | ✓ |
| predictions | 複数 ✓ | ✓ |
| knowledge | 不可算（例外） | ✓ |
| regime_assessments | 複数 ✓ | ✓ |
| event_reviews | 複数 ✓ | ✓ |
| skill_executions | 複数 ✓ | ✓ |

→ 6テーブル中5つが複数形。knowledgeは不可算名詞のため事実上の例外。**複数形が既存慣習**。

**DuckDBカラム名（現状）:**

| パターン | 例 | 準拠 |
|---------|-----|------|
| snake_case | event_timestamp, impact_reasoning, vix_value | ✓ 全カラム準拠 |
| PK | `id`（INTEGER） or `date`（DATE） | 混在（events.id vs regime_assessments.date） |
| FK | event_id, source_prediction_id | `{table}_id`パターン ✓ |
| タイムスタンプ | created_at, executed_at, discovered_date | `_at`（TIMESTAMP）と`_date`（DATE）が混在 |
| ブール | is_xxxパターンなし。outcome（BOOLEAN） | 明示的prefix なし |

**Parquetファイル名（現状）:**

| ディレクトリ | ファイル名 | パターン |
|------------|----------|---------|
| daily/ | `SOXL.parquet` | `{SYMBOL}.parquet`（大文字） |
| intraday/ | `SOXL_5min.parquet` | `{SYMBOL}_{interval}.parquet`（大文字） |
| macro/ | `BRENT.parquet`, `HY_SPREAD.parquet` | `{SERIES_ID}.parquet`（大文字） |

→ シンボル/シリーズ名は**大文字**（外部データソースの識別子をそのまま使用）。

## Decision

### 1. DuckDBテーブル名

| ルール | 根拠 |
|--------|------|
| **複数形** | 既存6テーブル中5つが複数形。変更コスト > 統一の利益 |
| **snake_case** | 業界標準 + DuckDB case-insensitive との相性 |
| **英語** | 既存踏襲 |

例: `trades`（✓）、`trade`（✗）

### 2. DuckDBカラム名

| ルール | 根拠 |
|--------|------|
| **snake_case、小文字** | 既存慣習 + 業界標準 |
| **PK: `id`**（INTEGER自動採番テーブル） | events, predictions, skill_executions で確立。regime_assessmentsの`date` PKは自然キーとして例外許容 |
| **FK: `{referenced_table_singular}_id`** | Ovid推奨。event_id, prediction_id で確立済み |
| **TIMESTAMP: `*_at`** | created_at, executed_at で確立。新規カラムも `_at` で統一 |
| **DATE: `*_date`** | discovered_date, review_date で確立。新規カラムも `_date` で統一 |
| **BOOLEAN: `is_*` または意味が明確な名詞** | outcome（predictions）は文脈上明確なため許容。新規追加時は `is_*` を推奨 |
| **スナップショット値: `{indicator}_at_entry` 等** | ADR-015で導入。疎結合のための値コピーであることを名前で示す |
| **ENUM的VARCHAR: 値は小文字snake_case** | category, status, impact, type 等。値の例: `risk_off`, `deposit`, `long`。大文字・キャメルケースは不可 |
| **DATE vs TIMESTAMP の使い分け** | 日単位の事実（取引日、期限日）= DATE。時刻精度が必要（作成日時、イベント発生時刻）= TIMESTAMP / TIMESTAMPTZ |

### 3. Parquetファイル名

| ルール | 根拠 |
|--------|------|
| **ディレクトリ: 小文字snake_case** | `daily/`, `intraday/`, `macro/`, `account/` |
| **ファイル: `{外部識別子}.parquet`** | 外部データソースの識別子をそのまま使う（SOXL, BRENT, HY_SPREAD）。大文字はソース由来であり、Master Senseiの命名規則ではない |
| **サフィックス: `_{interval}` で時間粒度を示す** | `SOXL_5min.parquet`。日足はサフィックスなし（デフォルト） |
| **account/: `transactions.parquet`** | 1ファイルで完結するため小文字。外部識別子ではなく内部名称 |

### 4. データベースファイル名

| ルール | 根拠 |
|--------|------|
| **`sensei.duckdb`** | 既存踏襲。プロジェクト名を反映 |

## 既存の不整合（許容）

| 箇所 | 不整合 | 対応 |
|------|--------|------|
| `knowledge` テーブル名 | 不可算名詞（複数形ルールの例外） | 既存のまま許容。リネームのコスト > 利益 |
| `regime_assessments.date` PK | 他テーブルは `id` がPK | 自然キー（日付でユニーク）として許容 |
| `predictions.outcome` | BOOLEAN だが `is_*` prefix なし | 文脈上明確。既存のまま許容 |
| `knowledge.id` が VARCHAR | 他テーブルは INTEGER | `K-001` 形式の文字列ID。既存のまま許容 |

## Consequences

- 新規テーブル・カラム追加時はこのADRを参照
- 既存の不整合はリネームしない（マイグレーションコスト > 利益）
- Parquetファイル名の大文字はソース由来であり規則違反ではない
- 見直しトリガー: テーブル数が15を超えた場合、または命名の判断に迷うケースが3回以上発生した場合

## References

- [Ovid: Database Naming Standards](https://dev.to/ovid/database-naming-standards-2061)
- [RootSoft: Database Naming Convention](https://github.com/RootSoft/Database-Naming-Convention)
- [Bytebase: SQL Table Naming Dilemma](https://www.bytebase.com/blog/sql-table-naming-dilemma-singular-vs-plural/)
