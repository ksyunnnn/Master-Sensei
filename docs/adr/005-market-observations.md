# ADR-005: 手動マクロデータ投入（market_observations）

Status: superseded by ADR-009
Date: 2026-03-27

## Context

FRED APIのデータ公開は1-2日遅延する。急変時（VIX急騰、原油急落等）にレジーム判定が古いデータに基づくと、判断の質が低下する。

feasibility_study/macroでは`market_data`テーブルに`source`カラムを持ち、FRED以外のソース（investing.com, cboe等）からの手動投入を許容していた。この仕組みがmaster_senseiにはない。

## Options

### A: Parquetにsourceカラムを追加

| 長所 | 短所 |
|------|------|
| 単一のデータソースで統一 | Parquetスキーマ変更が必要 |
| | 自動取得データと手動データの混在 |

### B: sensei.duckdbに`market_observations`テーブルを追加

| 長所 | 短所 |
|------|------|
| Parquet（自動）とDuckDB（手動）の責務分離が明確 | レジーム判定時に2箇所を参照する必要 |
| source/確認ステータスの管理が容易 | |
| ADR-001のハイブリッド戦略と整合 | |

### C: 手動投入しない（FRED遅延を受け入れる）

| 長所 | 短所 |
|------|------|
| 最もシンプル | 急変時に2日前のデータで判断。最も必要な時に最も古い |

## Decision

> **Option B: sensei.duckdbに`market_observations`テーブルを追加する。**

### テーブル設計

```sql
CREATE TABLE market_observations (
    date DATE NOT NULL,
    series VARCHAR NOT NULL,
    value DOUBLE NOT NULL,
    source VARCHAR NOT NULL,        -- 例: 'cboe', 'investing.com', 'web_search'
    observed_at TIMESTAMPTZ NOT NULL, -- 記録した日時（JST）
    status VARCHAR DEFAULT 'unverified', -- unverified / verified
    PRIMARY KEY (date, series, source)
)
```

### Write基準（ADR-003準拠）

| 条件 | Write? |
|------|--------|
| FREDデータが当日分を含まず、他ソースで当日値が確認できた | Yes |
| FREDデータが既に当日分を含んでいる | No（冗長） |
| ソースが不明確（「たぶんこれくらい」） | No |
| ソースURLまたはソース名を明記できる | Yes |

### レジーム判定時のデータ優先順位

1. `market_observations`の当日データ（最新のobserved_at）
2. Parquetの最新データ（FREDベース）
3. どちらもなければ欠損として扱う

### statusの運用

- `unverified`: Web検索等で取得した速報値
- `verified`: 後日FREDデータと照合して確認済み

## Rationale

- Charter 3.1（事実と推測の分離）: `source`と`status`で出所と信頼度を明示
- ADR-001（ハイブリッド戦略）: 更新が必要なデータ（status遷移）はDuckDB
- ADR-003（Write基準）: ソース明記が必須条件
- feasibility_study/macroの実績: 手動投入は実運用で有用だった（74イベント中、FRED以外ソースが30%以上）

## Consequences

- src/db.pyに`market_observations`テーブルとCRUDを追加
- assess_regime.pyを修正: Parquetに加えてmarket_observationsも参照
- セッション中にWeb検索で取得した値を記録する運用フローが可能になる
- 月次レビューでunverified値のFRED照合を実施
