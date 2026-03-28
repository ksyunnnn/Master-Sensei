# Condition

Last updated: 2026-03-28

## Current Condition

- Phase 3（運用サイクル確立）
- Charter v0.1.0（習熟度 Lv.1 見習い）
- 独立gitリポジトリ。ADR 8本、GDR 1本、87テスト全パス
- データ: Tiingo 10シンボル + FRED 9シリーズ + yfinance 3シリーズ
- sensei.duckdb: レジーム1件、予測1件（**解決済み、Brier 0.2025**）、知見6件（全件stale）、イベント1件、観測値3件
- Skills: `/verify-knowledge`, `/update-regime`（ADR-008で導入）

## Next Session Priority

1. **レジーム再判定** — データが3/26で2日古い。VIX 29.05, VIX/VIX3M 1.07。`/update-regime`で更新
2. **stale知見6件の検証** — 全件180日以上未検証。`/verify-knowledge`で対応
3. **GDR-001 Phase 1実装** — ADR-009作成→`source_prediction_id`, `root_cause_category`カラム追加、Brier 3成分分解関数
4. **予測#1ポストモーテムの知見化** — 確信度過信の分析をknowledge DBに記録（Kolbサイクル完遂の第一歩）

## フィードバックループの進捗

GDR-001で成長計測体系を設計。4領域12手法を調査し、3段階ロードマップを策定。
- Phase 1: `source_prediction_id`（Kolbサイクル）+ `root_cause_category`（失敗パターン）+ Brier 3成分分解 → **次セッションで実装**
- Phase 2: EPA + SRS + Error Budget Burn Rate → Lv.2到達時
- Phase 3: Calibration Curve + カテゴリ別分析 → Lv.3到達時

ADR-008でHook/Skill/CLAUDE.mdの責務分担を確立。トリガールールが機能する設計に改善済み。

## マクロ環境メモ（3/27時点）

- VIX 29.05（上昇加速）、VIX/VIX3M 1.07（バックワーデーション深化）
- イラン紛争: ホルムズ海峡封鎖継続、攻撃期限4/6。Brent $108
- 関税: IEEPA違憲→Section 122(10%)/301(80カ国調査)/232(自動車25%)で代替
- FRB: 3.50-3.75%据え置き、原油高で利下げ不能
- Great Rotation: テック→エネルギー・素材への大規模資金シフト
- SOXX -1.86σ、SOXL $49（月間-22%）

## Obstacles

- 予測蓄積が1件のみ（Brier計測開始したが統計的意味はN≧30から）
- stale知見6件が未検証のまま
- レジームデータが2日古い

## Completed

- [x] Phase 1-2: データ基盤 + レジーム判定
- [x] ADR-001〜008
- [x] GDR-001: 成長計測体系の設計（4領域12手法調査）
- [x] SessionStartフック: SenseiDB化 + [ACTION]フォーマット（ADR-008）
- [x] Stop Hook: command型に簡素化
- [x] Skills導入: `/verify-knowledge`, `/update-regime`
- [x] CLAUDE.md: トリガールール再設計、SQL所有権ルール追加
- [x] 予測#1解決: VIX<25 → False、Brier 0.2025（初計測）
- [x] yfinanceでVIX即時取得確認、ProviderChain実装
- [x] 銘柄追加（SQQQ/TNA/TZA/TECS）+ データ取得完了
