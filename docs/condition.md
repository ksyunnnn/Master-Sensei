# Condition

Last updated: 2026-03-27

## Current Condition

- Phase 3（運用サイクル確立）
- Charter v0.1.0（習熟度 Lv.1 見習い）
- 独立gitリポジトリ。ADR 7本、87テスト全パス
- データ: Tiingo 10シンボル + FRED 9シリーズ + yfinance 3シリーズ
- sensei.duckdb: レジーム1件、予測1件（3/28期限）、知見6件、イベント1件、観測値3件

## Next Session Priority

1. **予測#1の解決**（VIX<25 by 3/28、確信度45%。VIX 27.44で不利方向）
2. **フィードバック蓄積メカニズムの設計**（ADR-008）— 行動品質の改善ループが未設計
3. **ProviderChainのupdate_data.py/assess_regime.py統合**

## 未設計の課題: フィードバックループ

行動→フィードバック→改善のサイクルが設計されていない。
- ミスのパターン分類と再発検出がない
- フィードバックが行動ルール（CLAUDE.md）に接続されていない
- 予測事後検証→知見への自動フィードバックパスがない

## Obstacles

- 成長メカニズム7つ中、実質稼働ゼロ（予測蓄積待ち）
- 自律的問題発見が弱い（ユーザー修正8回）
- condition.md/ideal.mdの更新が遅れがち

## Completed

- [x] Phase 1-2: データ基盤 + レジーム判定
- [x] ADR-001〜007
- [x] SessionStartフック + CLAUDE.mdトリガールール
- [x] yfinanceでVIX即時取得確認、ProviderChain実装
- [x] 銘柄追加（SQQQ/TNA/TZA/TECS）+ データ取得完了
- [x] セッション知見の永続化（K-003〜006、イベント1件、観測値3件）
