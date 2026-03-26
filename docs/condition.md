# Condition

Last updated: 2026-03-26

## Current Condition

- Phase 1 完了。Phase 2 開始前
- Charter v0.1.0 策定済み（習熟度 Lv.1 見習い）
- データ基盤稼働中: FRED 9シリーズ + Tiingo 6シンボル（日足+5分足）
- 37テスト全パス
- sensei.duckdb は初回レジーム記録時に自動作成（スキーマ・CRUD実装済み）

## Obstacles

- レジーム判定ロジックが未実装（データはあるが分類ルールがない）
- 予測記録ゼロ（Brier score算出不可 → Lv.2昇格条件未達）
- macro.duckdbのイベント74件・レビュー45件は未移行（migrate.pyで移行可能、急ぎではない）

## Next Actions

- [ ] Phase 2: レジーム判定ロジック構築（VIX/VIX3M/HY_SPREAD/YIELD_CURVE等を使った自動分類）
- [ ] sensei.duckdb初期化（初回レジーム判定で自動作成）
- [ ] macro.duckdbからの任意移行（イベント・レビューの蓄積を引き継ぐ場合）

## Completed

- [x] docs/charter.md 策定（原則・自己評価メカニズム・習熟度定義）
- [x] docs/adr/001-storage-strategy.md（Parquet+DuckDBハイブリッド）
- [x] docs/adr/002-data-sources.md（FRED 9シリーズ + Tiingo 6シンボル）
- [x] docs/api-constraints.md（Tiingo Free tier制約・IEX上限10,000実測）
- [x] src/db.py, fred_client.py, tiingo_client.py, cache_manager.py 実装
- [x] tests/ 37テスト全パス
- [x] update_data.py CLIツール
- [x] .env APIキー設定
- [x] FRED 9シリーズ取得（~2,026行）
- [x] Tiingo日足6シンボル取得（~7,524行、2021-03〜）
- [x] Tiingo 5分足5シンボル取得（~50,000行、2025-09〜）
