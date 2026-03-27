# Condition

Last updated: 2026-03-27

## Current Condition

- Phase 3（運用サイクル確立）開始
- Charter v0.1.0（習熟度 Lv.1 見習い）
- データ基盤: FRED 9シリーズ + Tiingo 10シンボル（日足10 + 5分足8） + yfinance 3シリーズ
- プロバイダ抽象化: Protocol + ProviderChain（yfinance → FRED フォールバック）
- sensei.duckdb: レジーム1件、予測1件（未解決）、知見2件
- 87テスト全パス

## Latest Data (2026-03-27取得)

### yfinance (3/26確定値)
- VIX: 27.44 / VIX3M: 27.16 / Brent: $100.80

### FRED (公開遅延あり)
- VIX: 25.33 (3/25) / HY_SPREAD: 3.17 (3/25) / YIELD_CURVE: 0.46 (3/26)

### 予測#1
- VIXが25.0を下回る by 3/28（確信度45%）— **VIX 27.44で不利方向**

## Obstacles

- ProviderChainがupdate_data.py / assess_regime.pyに未統合（ADR-006のコードはあるが配線未完了）
- 予測1件のみ（Lv.2の30件には程遠い）
- 知見2件のみ（ともにmeta/自己限界の記録。市場パターンの知見ゼロ）
- condition.md / ideal.md の更新が遅れがち

## Next Actions

- [ ] ProviderChainをupdate_data.py / assess_regime.pyに統合
- [ ] 予測#1の解決（3/28期限）
- [ ] 市場パターンに基づく知見の蓄積開始
- [ ] condition.mdの更新を習慣化

## Completed

- [x] Phase 1: データ基盤（FRED 9 + Tiingo 6 → 10シンボル、37テスト）
- [x] Phase 2: レジーム判定（6指標MAP方式、31テスト）
- [x] ADR-001 ストレージ戦略（Parquet + DuckDB）
- [x] ADR-002 データソース選定（FRED 9 + Tiingo）
- [x] ADR-003 データガバナンス（Write基準・スキーマ変更基準）
- [x] ADR-004 銘柄選定基準（SQQQ/TNA/TZA/TECS追加）
- [x] ADR-005 手動マクロデータ投入（market_observations）
- [x] ADR-006 プロバイダ抽象化（Protocol + ProviderChain）
- [x] sensei.duckdb初期化、知見2件・予測1件記録
- [x] yfinanceでVIX/VIX3M/Brent即時取得確認
- [x] 差分取得バグ修正（5年分再取得問題、日中複数回実行対応）
- [x] git独立リポジトリ化
