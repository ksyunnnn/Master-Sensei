# 研究成果ストレージ設計（検討中）

Date: 2026-04-07
Status: 検討中（Obsidian概念の調査待ち）

## 背景

1000仮説→1本confirmed（H-18-03）の研究成果を、継続的な研究サイクルに活かせる形で保存する。

## 設計の根拠となるフレームワーク

| フレームワーク | 適用箇所 |
|--------------|---------|
| Design Science Research | Build→Evaluate→Reflect→Planのサイクル構造 |
| IMRaD | サイクル成果の凍結構造（1文書1問い） |
| Diátaxis | 入口（Tutorial）の必要性 |
| Cookiecutter-DS | データ・コード・レポートの配置規約 |
| Lab Notebook / Audit Trail | 過程記録は成果とは独立保存 |
| ADR | 方法論判断の記録は別文書で進化 |

## 決定済み事項

### 1. 機械可読データ（Parquet）

- **hypotheses.parquet**: 全仮説統合（Cat + H-XX + R2-XX）+ 結果status + cycle列
- **executions.parquet**: 全実行結果統合（signal_ideas + round2_results）+ cycle列
- 累積のみ、削除しない

### 2. 入口文書

- **data/research/README.md**: 短く保つ。現在地+次にやること+データカタログ+リンク集

### 3. 過程記録の分離（Lab Notebook原則）

- 成果（findings/）と過程（logs/）を分離
- サイクルごとに凍結、対の命名:
  - `findings/2026Q2-signal-exploration.md` — 成果
  - `logs/2026Q2-signal-exploration.log.md` — 過程

### 4. 参照資料の整理

- `references/` に不変資料を集約
  - hypothesis-space.md, ideation-catalog.parquet, ideation-report.md, polygon-data-reference.md

### 5. ADR-013 Lessons Learned

- docs/adr/013にセクション追記（研究データとは別の設計文書）

### 6. CSV→Parquet移行

- signal_ideas.csv, round2_results.csv, stage2_results.csv → executions.parquetに統合後CSV削除

## 未決事項

### Q2: 既存レポート3本の扱い

- final_evaluation.md, stage1_stage2_report.md, stage3_evaluation.md
- IMRaD原則（1文書1問い）vs 読者の利便性（1箇所で全体像）
- **Obsidian概念の調査後に決定**

## ユーザー要件（質問で確認済み）

- 研究は継続する（A: 同じファネル再実行 + B: 実運用フィードバック + C: 新アプローチ）
- 今すぐ次Cycleではない。マージ→整理→実運用が先
- データの用途: 「前回何を試して何がダメだったか」のクエリ + 実運用成績と研究データの比較
- 作業場所: 未定
