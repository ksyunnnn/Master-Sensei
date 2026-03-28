# ADR-001: ストレージ戦略（Parquet + DuckDB ハイブリッド）

Status: accepted
Date: 2026-03-26

## Context

Master Senseiは以下5種のデータを扱う:

1. 時系列価格データ（OHLCV、日足・5分足）— 大量、追記専用、分析クエリ中心
2. マクロ指標データ（VIX, Brent, US10Y等）— 中量、追記専用
3. イベントログ（マクロイベント、ニュース）— 追記専用、テキスト含む
4. 予測・判断記録 — 追記 + 後から結果更新（outcome fill-in）
5. 知見DB（学習パターン、ルール）— 小量、読み取り中心、状態更新あり

各データ種別に最適なストレージを選定する必要がある。

## Options

### A: 全データDuckDB

| 長所 | 短所 |
|------|------|
| 単一ファイルで管理簡単 | 価格データが大量になるとファイル肥大化 |
| SQLで全データ横断クエリ可能 | 同時書き込み不可（single writer） |
| スキーマ制約で整合性担保 | Parquetより可搬性低い |

### B: 全データParquet

| 長所 | 短所 |
|------|------|
| 可搬性高い、他ツールから読める | 行単位の更新不可（追記or全書き換え） |
| 圧縮効率が高い | SQLクエリには別途エンジン必要 |
| 並行読み取り安全 | スキーマ制約なし |

### C: ハイブリッド（Parquet + DuckDB）

| 長所 | 短所 |
|------|------|
| データ特性に合わせた最適化 | 2種のストレージ管理 |
| DuckDBからParquet直接クエリ可 | 設計の複雑さがやや増す |
| 更新が必要なデータはDuckDB、不変データはParquet | — |

## Decision

> **ハイブリッド戦略（Option C）を採用する。**

データ種別ごとの割り当て:

| データ | ストレージ | 理由 |
|--------|-----------|------|
| 価格データ（OHLCV） | **Parquet** | 追記専用・大量・分析特化。DuckDBから `read_parquet()` で直接クエリ |
| マクロ指標 | **Parquet** | 追記専用。シンボル別ファイルで管理 |
| イベントログ | **DuckDB** | テキスト検索・ステータス更新が必要 |
| 予測・判断記録 | **DuckDB** | outcome後日更新が必須。Brier score計算にSQL集約が便利 |
| 知見DB | **DuckDB** | 状態遷移（hypothesis→validated）あり。検索・フィルタ頻繁 |
| レジーム判定 | **DuckDB** | 推論根拠テキスト + 日次追記。クエリ頻繁 |

ファイル配置:
```
data/
├── parquet/
│   ├── daily/          # 日足: {SYMBOL}.parquet
│   ├── intraday/       # 5分足: {SYMBOL}_5min.parquet
│   └── macro/          # マクロ指標: {SERIES_ID}.parquet
└── sensei.duckdb       # イベント・予測・知見・レジーム
```

## Rationale

### DuckDB公式ドキュメントに基づく根拠

1. **DuckDBはParquetを直接クエリ可能**（duckdb.org/docs/data/parquet/overview）
   - `SELECT * FROM read_parquet('data.parquet')` でインポート不要
   - Projection pushdown: 必要カラムだけ読む
   - Predicate pushdown: 条件に合うrow groupだけ読む
   - VIEW定義で透過的にアクセス可能

2. **Parquetは行更新不可**（Apache Parquet仕様）
   - 列指向フォーマットのため、1行だけ更新はファイル全体の書き換えが必要
   - → 追記専用データ（価格・マクロ）に適する
   - → 更新が必要なデータ（予測のoutcome、知見のstatus）はDuckDB

3. **DuckDBの同時アクセス制限**（duckdb.org/docs/connect/concurrency）
   - Single writer制約あり
   - 本システムは単一プロセス（Claude Codeセッション）からのアクセスなので問題なし

4. **型の厳密さがクエリ性能に直結**（duckdb.org/docs/guides/performance/schema）
   - BIGINT vs VARCHAR で結合1.8倍、フィルタ4.3倍の差
   - DuckDBテーブルでは適切な型制約を設定する

## Consequences

- Parquetファイルの追記はPython（pandas/pyarrow）で行う
- DuckDBテーブルのスキーマはsrc/db.pyで管理（マイグレーション対応）
- 横断クエリ（価格×レジーム等）はDuckDBのVIEW経由で実現
- 見直しトリガー: Parquetファイルが100MB超、またはクエリ応答が1秒超になった場合
- ADR-009により、Parquetにsource/updated_at列を追加。生データの保存先をParquetに一本化
