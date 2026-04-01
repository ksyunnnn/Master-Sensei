# Condition

Last updated: 2026-04-01 (session 4)

## Current Condition

- Phase 3（運用サイクル確立）
- Charter v0.1.0（習熟度 Lv.1 見習い）
- 独立gitリポジトリ。ADR 17本、GDR 1本（Phase 1実装済み）、142テスト全パス
- データ: Tiingo 10シンボル + FRED 9シリーズ + yfinance 3シリーズ（ProviderChain統合済み）
- sensei.duckdb: レジーム6件、予測3件（解決1/未解決2、Brier 0.2025）、知見22件（K-022更新）、イベント89件、**トレード1件（SOXL +10%）**
- エントリーシグナル研究: @data/research/WIP-progress.md
- MCP DuckDB接続: `.mcp.json`（相対パス、read-only）でsensei.duckdbに接続
- Skills: `/verify-knowledge`, `/update-regime`, `/scan-market`, `/review-events`
- trades テーブル: ADR-015実装済み（add_trade, close_trade, review_trade）
- GDR-001 Phase 1: source_prediction_id, root_cause_category, Brier 3成分分解, Baseline Score, Kolbサイクル率

## Next Session Priority

1. **`/entry-analysis` スキル設計** — assess_regime() + assess_flow() の2軸をスキルに統合。後知恵バイアス排除
2. **4/3 Good Friday前の市場判断** — 4/1 ISM/ADP結果確認後。4/6ホルムズ期限が最大リスク
3. **予測モニタリング** — #2 SOXL $40割れ(55%, 4/11)、#3 SOXS +10%超(75%, 4/11)。#3の反証条件（VIX<25）が成立しつつある
4. **stale知見の検証** — 6件が180日以上未検証（SessionStart警告）
5. **エントリーシグナル研究** — (b) utils.py作成。詳細は @data/research/WIP-progress.md
6. **予測の追加記録** — 現在3件（解決1/未解決2）。Lv.2到達（N>=30）の最大ボトルネック

## 今セッションの成果（session 4, 4/1 午後）

### 設計・実装
- **assess_flow(): フロー評価関数の新設（ADR-017）** — レジーム（環境）と独立したフロー（勢い）の2軸評価
  - 4指標: PRICE_MOMENTUM, VIX_CHANGE, VOLUME_SURGE（方向連動型）, SIGMA_POSITION
  - 閾値は1年8銘柄の日足分位点に基づく。33テスト
  - VOLUME_SURGEの方向バイアスを検出・修正（下落+サージがbullish扱いになる問題）
  - 4シナリオ検証: 急騰日/下落日/急落日/平穏日で期待通りの判定（37/40点）
- **update_data.pyサマリー表示** — 更新後にマクロ/日足/5分足の最新値を一覧表示

### 日次ワークフロー
- データ全更新（マクロ9 + 日足10 + 5分足8）
- scan-market: 4件登録（カタール沖タンカー被弾、イスファハン製鉄所空爆、プレマーケットラリー、ISM/ADP予定）
- update-regime: risk_off維持（VIX 25.25→24.25で25閾値割れ、Brent $104.7→$100.3）
- review-events: 1件検証（Pentagon地上作戦準備: negative→neutral修正）

### 知見記録
- K-022更新: レジームとフローは独立した2軸（3/31 SOXL+17.9%が根拠）

### 前セッション（session 3, 3/31夜〜4/1未明）の成果
- SOXLロング+10%利確（Trade #1）、ADR-015/016、trades実装、scan-market 19件

### 前々セッション（session 2, 3/31）の成果
- エントリーシグナル研究: バイアス対策設計（ADR-013追記、K-020/021）

### 前々セッション（session 2, 3/31）の成果
- エントリーシグナル研究: バイアス対策設計（ADR-013追記、K-020/021）

## マクロ環境メモ（4/1 17:00 JST時点）

- レジーム: risk_off（スコア-0.5、neutral境界）
  - VIX 24.25 elevated（25閾値を明確に下回る）、VIX/VIX3M 0.949 contango回復
  - HY 3.46 widening（変化なし、信用市場は慎重）、Brent $100.3 crisis（改善方向）
- フロー（4/1時点）: TQQQ/SOXL neutral(+0.50)、TECL bullish(+0.70)
- 4/1プレマーケット: S&P先物+0.71%, Nasdaq+1.02%。和平期待で2日連続リスクオン
- イラン: Day33。カタール沖タンカー被弾（ミサイル1発命中）、イスファハン製鉄所2度目の空爆
- **4/6 ホルムズ期限** — 最重要イベント。交渉決裂→エスカレーション or 合意→原油急落
- 4/1夜: ISM製造業PMI（予想52.3）+ ADP雇用（予想+41K）。スタグフレーション確認リスク
- 4/3: NFP（Good Friday休場、反応は4/7月曜）
- 保有ポジション: **なし**

## フィードバックループの進捗

GDR-001 Phase 1実装完了。Kolbサイクル（予測→結果→知見→次の予測）の追跡が可能に。
- Phase 1: source_prediction_id + root_cause_category + Brier 3成分分解 → **実装済み**
- Phase 2: EPA + SRS + Error Budget Burn Rate → Lv.2到達時
- Phase 3: Calibration Curve + カテゴリ別分析 → Lv.3到達時

## 健康診断からの処方箋（3/29）

- 毎セッション1件以上の予測記録を厳守（Lv.2到達の最大ボトルネック）
- 確信度の幅を広げる（20%や80%も使う。40-55%に集中するとアンカリング疑い）
- instrument/riskカテゴリの知見を意識的に記録（meta偏重の是正）

## Obstacles

- 予測蓄積が3件のみ（Brier計測開始したが統計的意味はN>=30から）
- レジーム判定がrisk_offのみ（K-002: 判別力未検証）
- イベント#4と#63が重複（CME FedWatch 52%）。重複検出の仕組みが未整備
- Polygon.io Starter契約中（$29/月）。研究完了後に継続/解約を判断

## Completed

- [x] Phase 1-2: データ基盤 + レジーム判定
- [x] ADR-001〜010
- [x] GDR-001: 成長計測体系の設計 + Phase 1実装
- [x] SessionStartフック: SenseiDB化 + [ACTION]フォーマット（ADR-008）
- [x] Stop Hook: command型に簡素化
- [x] Skills導入: `/verify-knowledge`, `/update-regime`, `/scan-market`, `/review-events`
- [x] CLAUDE.md: トリガールール再設計、SQL所有権ルール追加
- [x] 予測#1解決: VIX<25 → False、Brier 0.2025（初計測）
- [x] 予測#1ポストモーテム: root_cause=overconfidence、K-007/K-014連鎖
- [x] ProviderChain統合: update_data.pyでyfinance→FRED自動フォールバック
- [x] ADR-009実装: スナップショット・source列・market_observations廃止・レビュー対応
- [x] ADR-010実装: /scan-market + /review-events + skill_executions
- [x] データ全更新 + レジーム再判定（3/28、risk_off）
- [x] 初回フルスキャン: 15ヶ月×6カテゴリ、32件登録、5知見記録
- [x] 知見全13件検証済み（staleゼロ）
- [x] 予測#2登録: SOXL $40割れ（55%、期限4/11）
- [x] /review-events初回実行: 34件検証、4件impact修正、レビュー率79%
- [x] ADR-011作成: GDR-001 Phase 1スキーマ変更の記録
- [x] ADR-012作成: スキル粒度設計の原則（5原則 + 日次ワークフロー定義）
- [x] MCP DuckDB接続: .mcp.json（相対パス、read-only）、旧設定削除、hookロック競合解消
- [x] scan-market SKILL.md: inline Pythonコメント除去（セキュリティ警告回避）
- [x] 日次ワークフロー初回完走: scan-market→update_data→update-regime→review-events
- [x] Memory運用設計: SoT確立 + キャッシュ層としてのMemory再構成
- [x] CLAUDE.md: Rules 2項目追記 + Memory運用ルールセクション追加
- [x] SKILL.md: scan-market/review-eventsにポジション影響シナリオ指針追加
- [x] SKILL.md: scan-market/review-eventsのheredoc方式移行（obfuscation警告解消）
- [x] ADR-013作成: エントリーシグナル研究方法論（3段階ファネル）
- [x] ADR-013追記: バイアス対策（反証テスト4種+カテゴリタイプ4種+プロンプト対策5点+情報アクセス設計）
- [x] アイデア生成: 21手法→67カテゴリ+3メタ+30設計原則（101件カタログ）
- [x] カテゴリタイプ分類: 68件→4タイプ（Parquetにbias_test_type/reason列追加）
- [x] ADR-014作成: Parquet Raw定義+スプリット調整方針
- [x] Polygon.io契約+18銘柄×5年分5分足OHLCV取得（3,456,034バー）
- [x] 予測#3登録: SOXS +10%超再出現（75%、期限4/11）
- [x] K-020/K-021登録: LLM Agentバイアス + Devil's Advocate最適形態
- [x] WIP-progress.md新設: 研究進捗のcondition.mdからの分離
- [x] polygon-data-reference.md新設: API仕様・データ特性記録
- [x] ADR-015: トレード記録のデータ設計 + trades実装（add/close/review_trade）
- [x] ADR-016: 命名規則の明文化
- [x] ADR-017: フロー評価関数 assess_flow()（4指標、方向連動VOLUME_SURGE）
- [x] update_data.py: サマリー表示機能（マクロ/日足/5分足の最新値一覧）
- [x] Trade #1: SOXLロング +10% ($120.15) 利確・記録
