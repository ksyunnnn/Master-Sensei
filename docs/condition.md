# Condition

Last updated: 2026-03-30

## Current Condition

- Phase 3（運用サイクル確立）
- Charter v0.1.0（習熟度 Lv.1 見習い）
- 独立gitリポジトリ。ADR 12本、GDR 1本（Phase 1実装済み）、99テスト全パス
- データ: Tiingo 10シンボル + FRED 9シリーズ + yfinance 3シリーズ（ProviderChain統合済み）
- sensei.duckdb: レジーム2件、予測2件（解決1/未解決1、Brier 0.2025）、知見16件（K-015更新、2件stale）、イベント50件、event_reviews 37件、skill_executions 6件
- MCP DuckDB接続: `.mcp.json`（相対パス、read-only）でsensei.duckdbに接続
- Skills: `/verify-knowledge`, `/update-regime`, `/scan-market`, `/review-events`
- GDR-001 Phase 1: source_prediction_id, root_cause_category, Brier 3成分分解, Baseline Score, Kolbサイクル率

## Next Session Priority

1. **予測#2のモニタリング** — SOXL $40割れ予測（期限4/11）。4/6イラン攻撃期限が最初の判定ポイント。K-015（期限延長パターン）で検証機会
2. **日次ワークフロー**（ADR-012）— scan-market → update_data.py → update-regime → review-events
3. **予測の追加記録** — 現在2件のみ。Lv.2到達（N>=30）の最大ボトルネック。毎セッション1件を目指す
4. **GDR-001 Phase 2検討** — EPA + SRS + Error Budget Burn Rate（Lv.2到達時の実装計画）

## 今セッションの成果

### MCP DuckDB接続修正
- `.mcp.json`作成: sensei.duckdbへの相対パス接続（`./data/sensei.duckdb`）
- `--read-only`モード採用: ADR-008（書き込みはSenseiDB経由）と整合、hookとのロック競合を解消
- 旧グローバル設定（backtest.duckdb）を`claude mcp remove`で削除

### /scan-market × 3回実行
- 6件のイベント登録（合計50件）:
  - USS Tripoli+3,500名中東到着（3/28）
  - Section 301強制労働調査60カ国開始（3/12、前回スキャン漏れ）
  - イランQalibaf「米軍を焼き殺す」警告（3/29）
  - パキスタンが米イラン対話ホスト表明（3/29）
  - Pentagon地上作戦準備（Kharg Island等、WaPo報道 3/28-29）
  - トランプ「イランは15項目の大部分に同意」主張（3/30、未検証）

### /review-events 実行
- 3件検証、2件impact修正:
  - Section 301強制労働調査: negative → neutral（調査段階で即時関税ではない）
  - トランプ攻撃期限延長: neutral → negative（市場は「不確実性の長期化」と解釈）
- K-015記録: 軍事期限延長パターン（hypothesis）

### ADR-012: スキル粒度設計の原則
- 5原則策定（単一責務、単独実行可能性、インフラ分離、外部オーケストレーション、検出/指示分離）
- CLAUDE.mdに日次ワークフロー・エントリー分析時データ更新ルールを追加
- 4スキルの分割維持を決定。update_data.pyはインフラとして位置づけ

### /update-regime 確認
- 3/30データで判定: risk_off（スコア-1.43）、前回と同一のため記録スキップ（ADR-003）

## マクロ環境メモ（3/30時点）

- レジーム: risk_off（スコア-1.43、3/30確認で変化なし）
- VIX 31.05（バックワーデーション1.061）。CME利上げ確率52%突破
- Brent $112.57（ホルムズ海峡封鎖継続、GS推定プレミアム$14-18）
- イラン: 停戦拒否、フーシ参戦、米軍被害。Pentagon地上作戦準備中。4/6攻撃期限
- トランプ「イランは大部分に同意」と主張（未検証）。パキスタンが対話ホスト表明
- S&P 500が200日MA下回り、Nasdaq・ダウ調整局面入り
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
