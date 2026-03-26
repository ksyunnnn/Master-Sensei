# Condition

Last updated: 2026-03-26

## Current Condition

- Phase 2 完了。Phase 3 開始前
- Charter v0.1.0（習熟度 Lv.1 見習い）
- データ基盤稼働中: FRED 9シリーズ + Tiingo 6シンボル（日足+5分足）
- レジーム判定ロジック実装済み。6指標独立スコアリング + 加重平均統合
- sensei.duckdb 初期化済み。初回レジーム判定記録: 2026-03-26 risk_off
- 68テスト全パス

## Latest Regime (2026-03-26)

risk_off (score: -1.0)
- VIX: high / VIXターム構造: backwardation / 原油: crisis
- HYスプレッド: normal / イールドカーブ: normal / ドル: normal

## Obstacles

- 予測記録ゼロ（Brier score算出不可 → Lv.2昇格条件未達）
- レジーム閾値は1年データのみで設計。歴史的危機データを含めると閾値が変わりうる
- macro.duckdbのイベント74件・レビュー45件は未移行

## Next Actions

- [ ] Phase 3: 予測記録・Brier Score計測の運用開始
- [ ] 閾値の妥当性検証（より長期のデータで確認）
- [ ] macro.duckdbからの任意移行（イベント・レビュー）

## Completed

- [x] Phase 1: データ基盤構築（FRED 9 + Tiingo 6、37テスト）
- [x] Phase 2: レジーム判定ロジック（6指標MAP方式、31テスト追加）
- [x] ADR-001〜003 策定
- [x] sensei.duckdb 初期化・初回レジーム記録
