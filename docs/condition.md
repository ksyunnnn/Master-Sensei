# Condition

Last updated: 2026-03-31

## Current Condition

- Phase 3（運用サイクル確立）
- Charter v0.1.0（習熟度 Lv.1 見習い）
- 独立gitリポジトリ。ADR 13本、GDR 1本（Phase 1実装済み）、99テスト全パス
- データ: Tiingo 10シンボル + FRED 9シリーズ + yfinance 3シリーズ（ProviderChain統合済み）
- sensei.duckdb: レジーム3件、予測3件（解決1/未解決2、Brier 0.2025）、知見19件、イベント67件
- エントリーシグナル研究: @data/research/WIP-progress.md
- MCP DuckDB接続: `.mcp.json`（相対パス、read-only）でsensei.duckdbに接続
- Skills: `/verify-knowledge`, `/update-regime`, `/scan-market`, `/review-events`
- GDR-001 Phase 1: source_prediction_id, root_cause_category, Brier 3成分分解, Baseline Score, Kolbサイクル率

## Next Session Priority

1. **エントリーシグナル研究の実行** — 詳細は @data/research/WIP-progress.md
2. **予測モニタリング** — #2 SOXL $40割れ(55%, 期限4/11)、#3 SOXS +10%超再出現(75%, 期限4/11)
3. **日次ワークフロー**（ADR-012）— scan-market → update_data.py → update-regime → review-events
4. **予測の追加記録** — 現在3件（解決1/未解決2）。Lv.2到達（N>=30）の最大ボトルネック

## 今セッションの成果

### 日次ワークフロー
- データ更新: 日足・5分足を3/30まで更新（1営業日分）
- scan-market: 3件イベント追加（Section 301半導体公聴会5/5-8、Tehran Toll Booth、S&P correction目前）。計67件
- update-regime: Parquetデータ日付が前回と同一のためスキップ（ADR-003準拠）
- review-events: 7件検証（1件impact修正: Section 301 negative→neutral）。重複1件発見(#4/#63)

### 予測記録
- 予測#3登録: SOXS +10%超再出現（75%、期限4/11）。MAP分析で確信度を導出

### エントリーシグナル研究
- データ品質検証(タスクa): 条件付き合格。リバーススプリット3件検出（TQQQ/SQQQ/SOXS）
- ADR-014策定: Parquetは生データ(Raw)保持、スプリット調整は読み込み時（業界標準準拠）
- Polygon.io Starter契約($29/月): Tiingo IEXにVolumeがない問題を解決。SIP全取引所合算Volume+取引回数(n)+バー内VWAP(vw)を取得可能に
- Polygonデータ取得(タスクa2): 18銘柄×5年分の5分足OHLCV（3,456,034バー、108.7 MB）
- Cat 68-72追加: Polygon固有フィールド（n, vw, 拡張時間帯）から5カテゴリ新規生成
- カタログ更新: 96→101件、推定仮説1,080-1,770→1,150-1,840
- WIP-progress.md新設: 研究進捗をcondition.mdから分離（別セッションでの消失防止）
- polygon-data-reference.md新設: API仕様・データ特性の記録（解約後の参照用）

## マクロ環境メモ（3/31時点）

- レジーム: risk_off（スコア-1.43、3/30判定で継続。データ同一のため3/31は再判定スキップ）
- VIX 30.61、VIX/VIX3M 1.051（バックワーデーション）
- HYスプレッド 3.42（3/27 FRED値、前回3.21から悪化）
- Brent: Parquet $108.65 / CNBC報道$112-115。月間+55-59%で史上最大月間上昇
- イラン: Day31。ホルムズ海峡にTehran Toll Booth体制確立（IRGC管理、$2M/隻、元建て決済）。Fortune: L字プラトーの可能性
- トランプがKharg Island・電力・淡水化施設の「完全破壊」を最後通牒（Truth Social）
- S&P 500: 6343.72でcorrection(-10%)まで1%未満。Nasdaq correction圏内。Q1マイナス確実
- SOXL 3/30: $40.62（-12.9%）。SOXS: $48.74（+13.1%）
- Section 301: 半導体明示対象の excess capacity公聴会 5/5-8。コメント締切4/15
- 今週注目: 4/3 NFP（Good Friday休場、反応は4/6）、4/6イラン攻撃期限

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
- [x] アイデア生成: 21手法→67カテゴリ+3メタ+30設計原則（101件カタログ）
- [x] ADR-014作成: Parquet Raw定義+スプリット調整方針
- [x] Polygon.io契約+18銘柄×5年分5分足OHLCV取得（3,456,034バー）
- [x] 予測#3登録: SOXS +10%超再出現（75%、期限4/11）
- [x] WIP-progress.md新設: 研究進捗のcondition.mdからの分離
- [x] polygon-data-reference.md新設: API仕様・データ特性記録
