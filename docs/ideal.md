# Ideal

## Phase 1: データ基盤構築

### Target Condition

Master Senseiが独立して動作するデータ基盤が完成している。FRED 9シリーズとTiingo 6シンボルのデータを自動取得・蓄積でき、レジーム判定が可能な状態。

### Key Results

- FRED 9シリーズのデータ取得・Parquet保存が動作する
- Tiingo 6シンボルの日足・5分足データ取得が動作する
- DuckDBに予測・知見・レジームのスキーマが存在する
- テストカバレッジ: 主要機能にユニットテストがある

### Done の定義

1. `python update_data.py` で全データが最新化される
2. sensei.duckdb にレジーム判定を記録できる
3. テストが全パスする

## Phase Map

| Phase | 概要 |
|-------|------|
| **Phase 1** | **データ基盤構築 ← 現在地** |
| Phase 2 | レジーム判定ロジック構築 |
| Phase 3 | 予測記録・Brier Score計測 |
| Phase 4 | 知見蓄積・自己評価メカニズム |
| Phase 5 | 総合アドバイザー機能 |
