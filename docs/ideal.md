# Ideal

## Phase 3: 運用サイクル確立

### Target Condition

データ取得→レジーム判定→予測記録→事後検証のサイクルが回っている状態。予測が30件蓄積され、Brier scoreによる自己評価が始まっている。

### Key Results

- 予測記録 >= 30件、うち解決済み >= 20件
- Brier score算出可能（Charter Lv.2条件）
- レジーム判定が最新データ（yfinance即時 + FRED公式）で実行される
- 知見DBが10件以上蓄積

### Done の定義

1. Brier scoreが算出可能で、月次レビューを1回実施
2. calibration curveが生成可能
3. get_bias_check()の全項目が判定可能（N >= 10）

## Phase Map

| Phase | 概要 | 状態 |
|-------|------|------|
| Phase 1 | データ基盤構築 | 完了 |
| Phase 2 | レジーム判定ロジック | 完了 |
| **Phase 3** | **運用サイクル確立 ← 現在地** |
| Phase 4 | 総合アドバイザー機能 |
