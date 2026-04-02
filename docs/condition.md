# Condition

Last updated: 2026-04-02 (session 7)

## Current Condition

- Phase 3（運用サイクル確立）
- Charter v0.1.0（習熟度 Lv.1 見習い）
- 独立gitリポジトリ。ADR 19本、GDR 1本（Phase 1実装済み）、152テスト全パス
- データ: Tiingo 10シンボル + FRED 9シリーズ + yfinance 3シリーズ（ProviderChain統合済み）
- sensei.duckdb: レジーム7件、予測3件（解決1/未解決2、Brier 0.2025）、知見23件、イベント105件、**トレード2件（#1 SOXL +10%利確済、#2 SOXL -0.04%スクラッチ決済）**
- エントリーシグナル研究: @data/research/WIP-progress.md
- MCP DuckDB接続: `.mcp.json`（相対パス、read-only）でsensei.duckdbに接続
- Skills: `/verify-knowledge`, `/update-regime`, `/scan-market`, `/review-events`, **`/entry-analysis`（NEW）**
- trades テーブル: ADR-015実装済み（add_trade, close_trade, review_trade）
- GDR-001 Phase 1: source_prediction_id, root_cause_category, Brier 3成分分解, Baseline Score, Kolbサイクル率

## Next Session Priority

1. **Trump演説結果の消化** — 演説(4/2 10:00 JST)の内容確認。和平具体策 vs NATO離脱強調で市場反応分岐
2. **��のエントリー機会の検討** — Trade #2スクラッチ決済済み。ノーポジション。演説後の方向性を見て再エントリーを検討
3. **予測モニタリング** — #2 SOXL $40割れ(55%, 4/11): $52.26で遠い。#3 SOXS +10%超(75%, 4/11): 反証条件VIX<25がほぼ成立(24.54)
4. **ISM物価78.3の中期影響評価** — Prices Paid大幅上振れ。和平が崩れた場合の売り加速リスク
5. **stale知見の検証** — 7件が180日以上未検証（SessionStart警告）
6. **予測の追加記録** — 現在3件（解決1/未解決2）。Lv.2到達の最大ボトルネック

## 今セッションの成果（session 7, 4/2 朝）

### Trade #2 決済・振り返り
- **Trade #2: SOXL long → スクラッチ決済** — $51.65→$51.631（-$0.49, -0.04%）
  - 日中高値$54.09(+4.7%)到達後、SLをBE($51.65)に引上げ→午後の戻しで約定
  - 引値$52.26。保持していればTP方向に進んでいた
  - **K-023登録**: 3xレバETFでエントリー当日のBE SL引上げは日中ボラ(2-3%)で刈られやすい

### 日次ワークフロー
- scan-market: 7件登録（4/1引け、イラン新攻撃、UK Hormuz会議、Brent<$100、Fed据置確認、ADP +62K、WH演説前ファクトシート）
- update-regime: risk_off維持（score -0.57）。Brent crisis→high改善、VIX/VIX3M contango→flat悪化が相殺
- 予測モニタリング: #2 $40割れ遠い、#3 反証条件ほぼ成立

### 前セッション（session 6, 4/1 夜）の成果
- Trade #2エントリー（$51.65×26株）、scan-market 5件、update_data.py --symbolオプション

### 前セッション（session 5, 4/1 夜）の成果
- `/entry-analysis` スキル実装（ADR-018）、compute_flow_inputs()、scan-market 4件

### 前セッション（session 4, 4/1 午後）の成果
- assess_flow()新設（ADR-017）、scan-market 4件、update-regime risk_off維持、review-events 1件

### 前セッション（session 3, 3/31夜〜4/1未明）の成果
- SOXLロング+10%利確（Trade #1）、ADR-015/016、trades実装、scan-market 19件

### 前々セッション（session 2, 3/31）の成果
- エントリーシグナル研究: バイアス対策設計（ADR-013追記、K-020/021）

## マクロ環境メモ（4/2 09:40 JST時点）

- レジーム: risk_off（スコア-0.57、前回-0.50）
  - VIX 24.54 elevated、VIX/VIX3M 0.987 flat、HY 3.28 widening、Brent $99.92 high
- 4/1引け: S&P +0.72%(6575)、Nasdaq +1.16%(21841)、SOXL $52.26(+9.1%)
- ISM物価78.3（2022年6月以来最高）、ADP +62K（予想+41K上振れ）
- WHがOperation Epic Fury「decisive success」ファクトシートを演説前に公開
- IRGC tech18社期限通過（00:30 JST）: tech企業への直接攻撃は未確認、軍事攻撃は継続
- **4/2 10:00 JST**: トランプ初プライムタイム演説 ← **あと20分**
- **4/6 ホルムズ期限** — 最重要イベント
- 4/3: NFP（Good Friday休場、反応は4/7月曜）
- 保有ポジション: **なし**（Trade #2スクラッチ決済済み）

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
- [x] Trade #2: SOXL long $51.65→$51.631 スクラッチ決済（BE SL引上げで刈られ）
- [x] K-023: 3xレバETFのBE SL知見（エントリー当日は日中ボラで刈られやすい）
- [x] ADR-019: 日時供給統一 — now_jst()/today_jst()に16箇所統一、SessionStart時刻注入、152テスト全パス
- [x] verify-knowledge: 8件検証（K-017 validated、K-018修正、6件検証日更新）
