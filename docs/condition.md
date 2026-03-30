# Condition

Last updated: 2026-03-30

## Current Condition

- Phase 3（運用サイクル確立）
- Charter v0.1.0（習熟度 Lv.1 見習い）
- 独立gitリポジトリ。ADR 12本、GDR 1本（Phase 1実装済み）、99テスト全パス
- データ: Tiingo 10シンボル + FRED 9シリーズ + yfinance 3シリーズ（ProviderChain統合済み）
- sensei.duckdb: レジーム3件、予測2件（解決1/未解決1、Brier 0.2025）、知見19件（K-017〜019追加、2件stale）、イベント55件、event_reviews 37件
- エントリーシグナル研究: ADR-013策定、data/research/作成、4 Agent並列検証体制設計済み
- MCP DuckDB接続: `.mcp.json`（相対パス、read-only）でsensei.duckdbに接続
- Skills: `/verify-knowledge`, `/update-regime`, `/scan-market`, `/review-events`
- GDR-001 Phase 1: source_prediction_id, root_cause_category, Brier 3成分分解, Baseline Score, Kolbサイクル率

## Next Session Priority

1. **エントリーシグナル研究の実行** — ADR-013 + hypothesis_space.md（30カテゴリ, ~1000仮説）に基づき4 Agent並列起動。残タスク: データ品質検証→utils.py作成→検出力分析→Agent起動→結果統合→10アイデア選定
2. **予測#2のモニタリング** — SOXL $40割れ予測（期限4/11）。4/6イラン攻撃期限が最初の判定ポイント
3. **日次ワークフロー**（ADR-012）— scan-market → update_data.py → update-regime → review-events
4. **予測の追加記録** — 現在2件のみ。Lv.2到達（N>=30）の最大ボトルネック

## 今セッションの成果

### scan-market実行（3回）+ update-regime
- 6件のイベント追加（Brent $115超、IRGC大学攻撃警告等）。登録済み: 55件
- レジーム再判定（3/30）: risk_off継続。Brent Parquet値$107.91とCNBC報道$115超に乖離あり

### エントリーSkill設計の調査・分析
- エントリータイミング分析: プレマーケット予測力なし(K-017)、30分なし(K-018)、60分微弱(K-018)、前日→翌日なし(K-019)
- 5分足データ拡張: backtest/から66日分結合（130日→197日）
- 6領域の方法論調査（統計学・クオンツ・A/Bテスト・創薬・ML・VC）→ 3段階スクリーニングファネル設計
- ADR-013策定、data/research/作成、4 Agent並列検証体制設計
- アイデア生成: 8手法適用（SCAMPER/逆ブレスト/前提反転/ビソシエーション/Zwicky Box/Po/ランダム刺激/ドメイン調査）→ 30カテゴリ・~1000仮説のhypothesis_space.md作成

## マクロ環境メモ（3/30時点）

- レジーム: risk_off（スコア-1.43、3/30再判定で継続）
- VIX 30.82（バックワーデーション1.053）。前日31.05から微減
- Brent: Parquet $107.91 / CNBC報道$115.35-$115.66（ソース間乖離あり。月間+55-59%で史上最大）
- イラン: Day30でIAFテヘラン120発超投下、イランはハイファ+ベングリオン空港に10波ミサイル。エスカレーション継続
- トランプ「イランは大部分に同意」と主張（未検証）。パキスタンが対話ホスト表明
- S&P 500が200日MA下回り調整局面。3/30先物は反発（S&P+0.46%）だが持続性不透明
- Fed funds先物が利上げ織り込みにシフト開始（CNBC報道）。10年債利回り4.4%超
- Section 301: 産業過剰16カ国 + 強制労働60カ国の2本立て。完了目標7/24
- 来週注目: 4/3雇用統計（予想+57K、前月-92K）、4/6イラン攻撃期限

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

- 予測蓄積が2件のみ（Brier計測開始したが統計的意味はN>=30から）
- レジーム判定がrisk_offのみ（K-002: 判別力未検証）
- /review-events: 3/28以降のイベント10件が3日経過後に対象（3/31以降）

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
