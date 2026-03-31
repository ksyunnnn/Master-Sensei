# WIP: エントリーシグナル研究 進捗

研究完了後にこのファイルは削除する。成果物は ideation_report.md / ideation_catalog.parquet / ADR-013 に残る。

## ファネル: 1000 → 100 → 10

> 1000のアイデアを検証し、100のアイデアを実験し、10のアイデアを実弾として提示する。

| 段階 | 対応 | 規模 | 状態 |
|------|------|------|------|
| **1000を検証** | Stage 1 スクリーニング（N≧30、方向一致率>50%） | 推定1150-1840仮説 | 未着手 |
| **100を実験** | Stage 2 統計検証（BH法p<0.20、Walk-forward、レジーム安定性） | Stage 1通過分 | 未着手 |
| **10を実弾** | Stage 3 実用性評価（JST制約・IFD-OCO適合・摩擦後期待値） | Stage 2通過分 | 未着手 |

## 残タスク

| # | タスク | 状態 | 依存 |
|---|--------|------|------|
| a | データ品質検証（Tiingo 5分足197日の整合性） | **条件付き合格** | — |
| a2 | Polygon 5分足データ取得（18銘柄×5年、OHLCV+n+vw） | **完了** | — |
| b | utils.py作成（一致率計算・BH法・Walk-forward・スプリット調整） | 未着手 | a, a2 |
| c | 検出力分析（Polygon 5年分でのMDE算出） | 未着手 | a2 |
| d | 4 Agent並列起動 | 未着手 | b, c |
| e | 結果統合（Stage 1→2→3フィルタ） | 未着手 | d |
| f | 10アイデア選定 | 未着手 | e |
| g | Skill/ツール設計・実装 | 未着手 | f |

## 設計メモ

- 口座残高・許容損失は実行時パラメータ（ハードコードしない）
- 出力: シナリオ分析 + 具体注文候補(複数) + 実証ベース推奨
- 手段はSkillに限定しない（Python CLI等も検討）
- feasibility_study/trading-rules.mdの旧ルールは無視。白紙から再設計
- ユーザーの発注パターン: (P1)開場前発注 / (P2)開場1h内 / (P3)開場3h内(避けたい)
- サマータイム中の開場: 22:30 JST（標準時: 23:30 JST）
- 未定義: MAP分析のスコアリング枠組み（3要素の定義、-2〜+2スケール、加重方法）。タスク(f)完了後に正式定義する

## タスク(a) 品質検証結果

- 重複: 0件、時系列順序: OK、NaN/ゼロ: なし、OHLC整合性: OK
- バー数: 全営業日78本で一貫（初日のみ部分日あり）
- **要対応**: リバーススプリット3件（TQQQ 2:1、SQQQ 5:1、SOXS 20:1）。5分足は未調整。ADR-014で対処方針を決定済み

## 完了済み

- [x] ADR-013設計（3段階ファネル、6領域参照方法論）
- [x] 仮説空間構築（hypothesis_space.md: 67カテゴリ+3メタ、1150-1840仮説）
- [x] 101件カタログ（ideation_catalog.parquet: 68シグナル+3メタ+30設計原則、出典付き）
- [x] 実証分析（プレマーケット→K-017、30/60分→K-018、前日リターン→K-019）
- [x] 5分足データ拡張（130→197日、backtest/から66日結合）

## 参照

- ADR-013: docs/adr/013-entry-signal-research-methodology.md
- ADR-014: docs/adr/014-parquet-raw-and-split-adjustment.md
- 仮説空間: data/research/hypothesis_space.md
- 調査レポート: data/research/ideation_report.md
- カタログ: data/research/ideation_catalog.parquet
- Polygonデータ: data/research/polygon_intraday/（取得後）
