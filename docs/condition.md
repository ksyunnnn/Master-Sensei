# Condition

Last updated: 2026-04-01 (session 5)

## Current Condition

- Phase 3（運用サイクル確立）
- Charter v0.1.0（習熟度 Lv.1 見習い）
- 独立gitリポジトリ。ADR 18本、GDR 1本（Phase 1実装済み）、150テスト全パス
- データ: Tiingo 10シンボル + FRED 9シリーズ + yfinance 3シリーズ（ProviderChain統合済み）
- sensei.duckdb: レジーム6件、予測3件（解決1/未解決2、Brier 0.2025）、知見22件、イベント93件、**トレード1件（SOXL +10%）**
- エントリーシグナル研究: @data/research/WIP-progress.md
- MCP DuckDB接続: `.mcp.json`（相対パス、read-only）でsensei.duckdbに接続
- Skills: `/verify-knowledge`, `/update-regime`, `/scan-market`, `/review-events`, **`/entry-analysis`（NEW）**
- trades テーブル: ADR-015実装済み（add_trade, close_trade, review_trade）
- GDR-001 Phase 1: source_prediction_id, root_cause_category, Brier 3成分分解, Baseline Score, Kolbサイクル率

## Next Session Priority

1. **`/entry-analysis` 実戦テスト** — 実際にスキルを実行して出力フォーマットを調整する
2. **4/2 トランプ演説後の市場判断** — 演説(4/2 10:00 JST)の結果確認。4/6ホルムズ期限が最大リスク
3. **IRGC tech脅威の影響確認** — 4/2 00:30 JST攻撃開始期限。SOXL/TQQQ/TECL構成銘柄直撃
4. **予測モニタリング** — #2 SOXL $40割れ(55%, 4/11)、#3 SOXS +10%超(75%, 4/11)。#3の反証条件（VIX<25）が成立しつつある
5. **stale知見の検証** — 7件が180日以上未検証（SessionStart警告）
6. **予測の追加記録** — 現在3件（解決1/未解決2）。Lv.2到達（N>=30）の最大ボトルネック

## 今セッションの成果（session 5, 4/1 夜）

### 設計・実装
- **`/entry-analysis` スキル実装（ADR-018）** — MAP分析→シナリオ別注文設定→trade記録の1フロー
  - 3軸MAP: Regime(assess_regime) + Flow(assess_flow) + Event Risk(DuckDB events)
  - `compute_flow_inputs()`: Parquetからassess_flow()入力値を自動計算（8テスト追加）
  - シナリオはテンプレ固定せず動的構築。TP/SLはσ・SMAから統計的根拠
  - Confidence: Master Senseiが3段階提示→ユーザー選択
  - 自己評価でSession 3アンカリング・複雑性バイアスを検出→最小版に絞り込み
  - レビューで3件修正（get_open→get_pending、5分足記述削除、知見フィルタ撤去）

### 日次ワークフロー
- scan-market: 4件登録（クウェート空港ドローン攻撃、IRGC tech18社脅威、トランプ演説予定、ベイルート空爆）
- update-regime: risk_off維持（変化なし。VIX 24.3, Brent $101.5）。トランプ演説後に再評価予定

### 前セッション（session 4, 4/1 午後）の成果
- assess_flow()新設（ADR-017）、scan-market 4件、update-regime risk_off維持、review-events 1件

### 前セッション（session 3, 3/31夜〜4/1未明）の成果
- SOXLロング+10%利確（Trade #1）、ADR-015/016、trades実装、scan-market 19件

### 前々セッション（session 2, 3/31）の成果
- エントリーシグナル研究: バイアス対策設計（ADR-013追記、K-020/021）

### 前々セッション（session 2, 3/31）の成果
- エントリーシグナル研究: バイアス対策設計（ADR-013追記、K-020/021）

## マクロ環境メモ（4/1 21:00 JST時点）

- レジーム: risk_off（スコア-0.71）
  - VIX 24.3 elevated、VIX/VIX3M 0.951 flat、HY 3.46 widening、Brent $101.5 crisis
- イラン: Day33。クウェート空港ドローン攻撃（湾岸全域に波及）、IRGC がNVIDIA/Apple等18社を「正当な標的」宣言
- **4/2 00:30 JST**: IRGC攻撃開始期限。SOXL/TQQQ/TECL構成銘柄に直接関連
- **4/2 10:00 JST**: トランプ初プライムタイム演説。「2-3週間で終わる」発言。停戦/エスカレ両面リスク
- **4/6 ホルムズ期限** — 最重要イベント
- 4/1夜: ISM製造業PMI（23:00 JST）+ ADP雇用。結果未確認
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
- [x] ADR-018: /entry-analysis スキル（最小版）— MAP 3軸+シナリオ別注文設定+trade記録
- [x] compute_flow_inputs(): Parquet→assess_flow入力の自動計算（8テスト追加、150テスト全パス）
