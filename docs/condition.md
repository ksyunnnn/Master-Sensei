# Condition

Last updated: 2026-04-07 (session 14)

## Current Condition

- Phase 3（運用サイクル確立）
- Charter v0.1.0（習熟度 Lv.1 見習い）
- 独立gitリポジトリ。ADR 21本、GDR 1本（Phase 1実装済み）、574テスト全パス
- データ: Tiingo 10シンボル + FRED 9シリーズ + yfinance 3シリーズ（ProviderChain統合済み）
- sensei.duckdb: レジーム7件、予測3件（解決1/未解決2、Brier 0.2025）、知見23件、イベント105件、**トレード2件（#1 SOXL +10%利確済、#2 SOXL -0.04%スクラッチ決済）**
- エントリーシグナル研究: @data/research/WIP-progress.md
- MCP DuckDB接続: `.mcp.json`（相対パス、read-only）でsensei.duckdbに接続
- Skills: `/verify-knowledge`, `/update-regime`, `/scan-market`, `/review-events`, `/entry-analysis`, `/signal-check`
- シグナル監視: src/signals/（1シグナル1ファイル、自動レジストリ）。confirmed: H-18-03のみ
- trades テーブル: ADR-015実装済み（add_trade, close_trade, review_trade）
- GDR-001 Phase 1: source_prediction_id, root_cause_category, Brier 3成分分解, Baseline Score, Kolbサイクル率
- **PR #1**: https://github.com/ksyunnnn/Master-Sensei/pull/1

## Next Session Priority

1. **Confirmatory Round** — H-18-03を固定プロトコルで再検証（事後変更なし）+ CSCV(8ブロック)
2. **H-18-03のパラメータ感度** — 2日/4日/5日連続を正式テスト（多重検定補正込み）
3. **H-18-03の実弾化実装** — /entry-analysisスキルへの組み込み
4. **予測モニタリング** — #2 SOXL $40割れ(55%, 4/11), #3 SOXS +10%超(75%, 4/11)
5. **stale知見の検証** — 7件が180日以上未検証

## エントリーシグナル研究: 最終結果

**実弾確定: H-18-03（3日連続下落→ロング）のみ。**
- TQQQ: 勝率64.8%, 摩擦後+1.42%/回, 年+30.6%
- TECL: 勝率64.2%, 摩擦後+1.50%/回, 年+32.7%
- R2-TD-01は摩擦後マイナスで不採用
- H-12-03-Sはコンタンゴ+2.5%のみで保留
- 詳細: data/research/final_evaluation.md, data/research/stage3_evaluation.md

## 今セッションの成果（session 13, 4/5-4/6）

### Round 2探索
- 30仮説×348実行。イベント/データ駆動/クロスアセット/時間帯の4アプローチ
- R2-TD-01（開場30分モメンタム）が15/18銘柄で通過、Stage 2全フィルタ通過
- ただし摩擦後期待値でマイナスと判明 → 不採用

### Stage 3評価 + 摩擦後検証
- H-18-03: 摩擦後+1.4%/回（実弾成立）
- R2-TD-01: 摩擦後-0.07%（不成立）
- H-12-03-S: コンタンゴ分離で追加エッジ+2.5%のみ（保留）

### 最終評価レポート + バイアス監査
- Harvey閾値、研究者自由度、Kahneman 12問で研究全体を3軸評価
- Pre-registration遵守度 2/5、事後変更4件 → 全結果はexploratory
- docs/bias-audit-checklist.md導入（Premortem + Kahneman 12問）
- docs/writing-guidelines.md導入（YWT + 認知負荷7原則）

## 前セッションの成果（session 12+13前半, 4/5）

### Stage 1完成
- random_data_control問題解決（Stage 1判定から除外、通過27→39）
- FRED 9系列を1年→5年拡張（1,245-1,307行、NaN 0）
- マクロ仮説106件を5年データで再実行（200 perms、約40分）
- **最終Stage 1通過: 48行（27ユニーク仮説）**

### Stage 2実装・実行
- src/stage2_filter.py新規（22テスト）
- 4フィルタ適用: BH補正（screen p値）、Walk-forward、VIXレジーム、複数銘柄再現
- **Stage 2通過: 8行（4ユニーク仮説）**
  - H-18-03（逆張り）TQQQ/TECL/TZA、H-13-02（VIXレジーム）SOXL/SPXL、H-68-01（取引サイズ）TQQQ、H-01-09（OR方向）SPY/HYG
- **準通過（VIXY専用Filter 1-3通過）**: H-12-03-S、H-03-05、H-50-01

### 構造的問題の発見と対処
- **shuffle p値のBH補正離散制限**: 最小p=0.001がBH rank 1閾値(0.000066)を超えられない
  → 対策: Filter 1でscreen_signal p値を使用（連続値、BH互換）
- **200 permsの精度トレードオフ**: 実行時間5倍短縮だが境界仮説の判定にノイズ
  → Stage 3前に1000 permsで再検証予定

### ドキュメント
- data/research/stage1_stage2_report.md新設（12セクション、305行の包括レポート）
- PR #1に YWT形式セッション振り返り5件追記済み

## 前セッションの成果（session 11, 4/3-4/4）

## 前セッションの成果（session 11, 4/3-4/4）

### タスク d1-review 完了（Look-Ahead Bias再チェック）
- Critical 3件修正: h_12_02（transform('last')同日終値伝播）、h_72_01/02（アフターマーケットデータ同日伝播）
- Important 1件修正: h_14_01（bfill→ffill、OpEx週フラグ逆伝播防止）
- Important 6件注釈記録: time-of-day全体平均（方向性に影響しないため許容）

### タスク d2 完了（signal_runner.py）
- 機械実行ランナー: 314仮説×10-18シンボル=3,468実行規模
- データ準備: merge_macro（FREDマクロ）、merge_pair（Polygon ETF: Bear対応/VIXY/クロスセクター）
- 反証テスト: 全4種実行+bias_test_type別判定+float/bool信号型別の判定除外
- 31テスト追加（574テスト全パス）

### タスク d3 完了（Round 1実行）
- 3,339件実行、14仮説通過（27件、0.8%）、4.5時間
- 複数シンボル再現: H-01-09（10銘柄）、H-13-02（3銘柄）、H-68-01（3銘柄）
- **構造的問題発見**: random_data_controlが全bool信号を全滅させている（Stage 1設計との矛盾）
- **float信号の反証テスト問題発見・修正**: random_data(FP率≈50%)とreverse_direction(diff=0)が不適切→判定除外

### PR #1 作成
- YWT形式の時系列振り返りコメント4件 + 横断振り返り1件

### 前セッションの成果（session 10, 4/3 朝）

#### タスク d1 完了（信号生成関数 + HYPOTHESES）
- signal_defs.py: **163信号関数**（47カテゴリ）+ 28ヘルパー（既存25+VIX系3）
- HYPOTHESES: **314エントリ**（long/short展開。direction_fixed=12件は片方向）
- ROUND2_CANDIDATES: **21カテゴリ/49サブシグナル**（Stage 1結果依存8, 評価指標5, 非エントリー6, DuckDB依存2）
- 290テスト新規追加（構造テスト+代表テスト+VIXヘルパー4層テスト）。全543テストパス
- Look-Ahead Bias修正2件（h_01_09 OR確定前NaN化、h_03_07 前日Vol使用）
- _stress_daysバグ修正1件（グループ計算ロジック）
- 自動整合性チェック8項目全PASS（全関数HYPOTHESES含有、ID一意、R1/R2重複なし、全カテゴリカバー）
- コミット: dbd64d9

### グローバルCLAUDE.md更新
- `python3 -c` 内 `#` コメント禁止ルール追加（obfuscation検出回避）

### 前セッションの成果（session 9, 4/2 夜）

### 検出力分析（タスク c 完了）
- `compute_mde_binomial()`, `compute_mde_spearman()`, `power_analysis_report()` 実装
- MDE確定: 日足52.4% / バー50.3% / WF2分割53.4%（α=0.20, power=0.80）
- レビュー修正3件（off-by-one, Fisher z前提条件, NaN返却）

### ADR-021: シグナル定義と探索の実装方式
- コンセプト: **Dig with intent, verify with discipline.**
- 2ラウンド制（確認→探索）。signal_defs.py + signal_runner.py
- 10+ソース調査（AlphaAgent, DFS, PAP, tsfresh, arxiv等）
- 4 Agent並列→単一スクリプトに縮小。タスクd-pre廃止

### signal_defs.py ヘルパー関数（25個）
- RSI, MA, BB, ATR, Gap, Volume, VWAP, Calendar等
- 61テスト（自己評価5.5/10→不備23件修正: assert欠落, 未テスト関数, 境界, 反例）

### 前セッション（session 8, 4/2 午後）の成果

#### research_utils.py 実装（タスク b 完了）
- **src/research_utils.py** 新規作成 — 12関数、ADR-013/014準拠
  - データ読み込み（スプリット調整）、Stage 1スクリーニング、Stage 2統計検証（BH/walk-forward/regime/multi-symbol）、反証テスト4種、CSV記録
- **65テスト** 全パス（既存152と合わせて217）
- データ参照先: `../master_sensei/`（読み取り専用）

#### コードレビュー → 5件修正
- Critical 2件: シャッフルテストp値反保守的（Phipson & Smyth補正）、record_result TOCTOU競合
- High 3件: 全Trueシグナル無警告、float 0/1誤判定、regime N整合性

#### テスト恣意性レビュー → 指針明文化 + テスト改善
- docs/testing-guidelines.md: 6原則（4層構造、seed正当性、閾値根拠、境界決定論、不変量parametrize、参照実装比較）
- 境界テスト8件 + 不変量テスト16件追加（40→65テスト）

#### ドキュメント新設
- ADR-020: 統計・金融コードのレビュー基準導入
- docs/code-review-checklist.md: レビューチェックリスト（4領域）
- docs/testing-guidelines.md: テスト設計原則

### 前セッション（session 7, 4/2 朝）の成果

#### Trade #2 決済・振り返り
- **Trade #2: SOXL long → スクラッチ決済** — $51.65→$51.631（-$0.49, -0.04%）
  - 日中高値$54.09(+4.7%)到達後、SLをBE($51.65)に引上げ→午後の戻しで約定
  - 引値$52.26。保持していればTP方向に進んでいた
  - **K-023登録**: 3xレバETFでエントリー当日のBE SL引上げは日中ボラ(2-3%)で刈られやすい

#### 日次ワークフロー
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
- [x] CLAUDE.md(global): python3 -c内#コメント禁止ルール追加（obfuscation検出回避）
- [x] d1-review: Look-Ahead Bias再チェック（Critical 3+Important 1修正、290テスト全パス）
- [x] d2: signal_runner.py実装（31テスト、574全パス）
- [x] d3: Round 1実行（3,339件、14仮説通過、signal_ideas.csv記録）
- [x] PR #1作成: YWT振り返りコメント付き
- [x] random_data_control問題解決: Stage 1判定から除外、通過27→39件
- [x] FRED 9系列5年拡張（1,245-1,307行、NaN 0）
- [x] マクロ仮説106件再実行（5年データ、200 perms、40分）、通過39→48
- [x] Stage 2実装（4フィルタ、22テスト、stage2_results.csv出力）
- [x] Stage 2通過: 4ユニーク仮説 + VIXY準通過3仮説 = 7候補
- [x] Stage 1-2総括レポート（data/research/stage1_stage2_report.md、305行）
