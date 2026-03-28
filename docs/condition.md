# Condition

Last updated: 2026-03-29

## Current Condition

- Phase 3（運用サイクル確立）
- Charter v0.1.0（習熟度 Lv.1 見習い）
- 独立gitリポジトリ。ADR 9本、GDR 1本、89テスト全パス
- データ: Tiingo 10シンボル + FRED 9シリーズ + yfinance 3シリーズ（ProviderChain統合済み）
- sensei.duckdb: レジーム2件、予測1件（解決済み、Brier 0.2025）、知見8件（7件stale）、イベント12件、skill_executions 1件
- Skills: `/verify-knowledge`, `/update-regime`, `/scan-market`, `/review-events`
- DB: events.source列追加（manual/scan-market識別）、skill_executionsテーブル新設

## Next Session Priority

1. **初回フルスキャン（/scan-market 拡大版、ADR-010参照）**
   - 対象: 2025年1月〜現在（15ヶ月）。トランプ政策経緯と季節性を把握するため
   - 検索方法: 四半期（Q1-Q4 2025, Q1 2026）× 6カテゴリ（地政学/FRB/半導体/原油/関税/市場）で分割検索。クエリに必ず年月を含める
   - フィルタ: ADR-003基準（対象シンボルへの影響）のみ。レジーム関連性では絞らない（確証バイアス排除）
   - 検証: 定性イベントは2ソース以上で確認、定量はParquet照合、Tier 3ソース不可（ADR-010 品質基準）
   - 完了後: トランプ政策パターン・季節性等を知見DB（knowledgeテーブル）に記録。根拠となるevent IDをevidenceに引用
2. **stale知見7件の検証** — `/verify-knowledge`で対応
3. **GDR-001 Phase 1実装** — source_prediction_id, root_cause_category, Brier 3成分分解
4. **予測#1ポストモーテムの知見化** — 確信度過信の分析をknowledge DBに記録

## 今セッションの成果

### ADR-009: データ保存先の責務分離の徹底
- 生データの保存先をParquetに一本化（ADR-001原則の回復）
- regime_assessmentsに入力値スナップショット6カラム追加（Decision Tracking原則）
- Parquetにsource/updated_at列追加（行レベルのソース追跡）
- market_observations廃止（ADR-005 supersede）
- update_data.pyをProviderChain方式に切り替え
- assess_regime.pyのマージ処理を削除・簡素化
- 89テスト全パス、レビュー指摘3件対応済み

### スキル追加
- `/scan-market`: WebSearchで6カテゴリのニュース調査 → イベント登録
- `/review-events`: イベントのimpact事後検証 → lesson記録

### 実運用
- データ全更新実施（ProviderChain初回運用成功）
- レジーム再判定: risk_off（スコア-1.43）、スナップショット付きで記録
- `/scan-market`初回実行: 6件のイベントを登録

## マクロ環境メモ（3/28時点）

- VIX 31.05（+13.16%）、VIX/VIX3M 1.061（バックワーデーション深化）
- イラン: 米停戦15項目案を拒否、独自5条件提示。トランプがエネルギーインフラ攻撃期限を4/6に延長
- Brent $112.57（+4.22%）、2022年7月以来の高値。GS推定リスクプレミアム$14-18
- FRB: 3.50-3.75%据え置き。CME先物で年内利上げ確率が初めて52%突破
- SOX -2.9%、NVIDIA -4%（3ヶ月安値）。SOXL $46.61（2日で-21%）
- S&P 500 -1.67%、Nasdaq -2.15%。Nasdaq調整局面入り

## フィードバックループの進捗

GDR-001で成長計測体系を設計。4領域12手法を調査し、3段階ロードマップを策定。
- Phase 1: source_prediction_id + root_cause_category + Brier 3成分分解 → 次セッションで実装
- Phase 2: EPA + SRS + Error Budget Burn Rate → Lv.2到達時
- Phase 3: Calibration Curve + カテゴリ別分析 → Lv.3到達時

ADR-008でHook/Skill/CLAUDE.mdの責務分担を確立。ADR-009でデータ保存先の原則を徹底。

## Obstacles

- 予測蓄積が1件のみ（Brier計測開始したが統計的意味はN>=30から）
- stale知見7件が未検証のまま（K-008は新規追加で検証済み）
- scan-marketの調査期間管理が未完成（source列/scan_history設計中）

## Completed

- [x] Phase 1-2: データ基盤 + レジーム判定
- [x] ADR-001〜009
- [x] GDR-001: 成長計測体系の設計（4領域12手法調査）
- [x] SessionStartフック: SenseiDB化 + [ACTION]フォーマット（ADR-008）
- [x] Stop Hook: command型に簡素化
- [x] Skills導入: `/verify-knowledge`, `/update-regime`, `/scan-market`, `/review-events`
- [x] CLAUDE.md: トリガールール再設計、SQL所有権ルール追加
- [x] 予測#1解決: VIX<25 → False、Brier 0.2025（初計測）
- [x] ProviderChain統合: update_data.pyでyfinance→FRED自動フォールバック
- [x] ADR-009実装: スナップショット・source列・market_observations廃止・レビュー対応
- [x] データ全更新 + レジーム再判定（3/28、risk_off）
- [x] /scan-market初回実行: 6件イベント登録
- [x] 知見K-008記録: FREDデータ改訂の検出方法
