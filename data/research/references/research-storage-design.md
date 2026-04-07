# 研究成果ストレージ設計

Date: 2026-04-07
Status: 確定

## 背景

1000仮説→1本confirmed（H-18-03）の研究成果を、継続的な研究サイクルに活かせる形で保存する。研究は継続する（同じファネル再実行、実運用フィードバック、新アプローチの全て）。

## 設計に至る調査経緯

### 出発点: 研究成果の記録フォーマットが未設計だった

研究プロセス（仮説生成→検証→評価）の実装は完了したが、成果を「将来の自分が再利用できる」形で保存する設計がなかった。CSVが3本、Markdownレポートが5本、Parquetが1本が data/research/ に散在し、相互関係が不明確だった。

### 調査1: ベンチマークとなるジャンル

6ジャンルを比較した。

| ジャンル | 目的 | 個人研究への適合性 |
|---------|------|------------------|
| 学術論文（IMRaD） | 発見の公表・検証 | 低（コード不在、スナップショット） |
| テクニカルレポート | 社内意思決定 | 中（構造的だが再実行不可） |
| **Reproducible Report (Quarto)** | コード+結果+結論の一体記録 | **高**（パラメータ化で再実行可能） |
| **Cookiecutter-DS** | プロジェクト全体の整理 | **高**（データパイプライン再現性） |
| **Lab Notebook** | 過程の時系列記録 | **中-高**（探索的、設計次第） |
| Quant特有（LEAN Report等） | バックテスト結果の標準可視化 | 中（結果表示特化） |

**結論**: Cookiecutter-DS（骨格）+ Reproducible Report（成果凍結）+ Lab Notebook（過程記録）の3層構成を採用。

### 調査2: 継続研究のサイクル管理

Design Science Research（Hevner 2004）のBuild→Evaluate→Reflect→Planサイクルをベースに、各フェーズの成果物を定義:

- **Build**: hypotheses.parquet（何を作ったか）
- **Evaluate**: executions.parquet（結果の数値）
- **Reflect**: findings/（なぜそうなったか、判断経緯）
- **Plan**: README.md（次にどこから始めるか）

「Reflect→Plan」の接続が研究継続の鍵。ADR-013のLessons Learnedが次サイクルの設計を改善する。

### 調査3: 既存資産の棚卸しで発見した5つの問題

| # | 問題 | 影響 |
|---|------|------|
| 1 | ideation_catalog（Cat-XX）とsignal_ideas（H-XX-XX）のjoinが暗黙的 | カテゴリ単位の分析不可 |
| 2 | Round 2仮説（R2-XX）がカタログに未登録 | 管理外、次回重複リスク |
| 3 | CSVが3つ別々で横断クエリ困難 | 分析効率低下 |
| 4 | WIP-progress.mdが作業ログ・研究状態・気づきを兼務 | 検索性低下 |
| 5 | ADR-013が当初設計のまま | 教訓が方法論に還元されない |

### 調査4: 「分割しつつ全体像が見える」構造

IMRaD原則（1文書1問い）では既存レポート3本が分かれるが、読者は1箇所で全体像を掴みたい。

Obsidianが推奨する3概念を調査:

| 概念 | 核心 | 適合度 |
|------|------|--------|
| **MOC (Map of Content)** | ハブ文書がAtomic Notesへのリンクを束ね、全体像を提供 | **最高** |
| **Atomic Notes** | 1ノート1概念。IMRaDの「1文書1問い」と同義 | 高 |
| **Evergreen Notes** | 凍結せず進化し続けるノート | 中（README.mdの性質） |

**結論**: MOC + Atomic Notes構成を採用。findings/にMOC 1本（全体像+判断経緯+リンク）+ 詳細3本（Atomic、各1問いに回答）。

### 調査5: 過程記録の配置

Lab Notebook原則（Lincoln & Guba 1985, Audit Trail）とCookiecutter-DS:
- 過程記録は成果とは**独立して保存**すべき
- 成果物は結論を伝える目的、過程記録は検証可能性の目的。混ぜると両方が中途半端になる

**結論**: findings/（成果）とlogs/（過程）を分離。サイクルごとに対の命名で凍結。

## 最終設計

### ディレクトリ構成

```
data/research/
  README.md                                  ← 入口（Evergreen、サイクルごとに更新）
  hypotheses.parquet                         ← 全仮説（累積、cycle列で世代管理）
  executions.parquet                         ← 全実行結果（累積、cycle列で世代管理）
  
  findings/                                  ← サイクル成果（凍結）
    2026Q2-signal-exploration.md             ← MOC（全体像+判断経緯+リンク）
    2026Q2-methodology-evaluation.md         ← Atomic: 方法論評価
    2026Q2-stage1-stage2-results.md          ← Atomic: Stage 1-2結果
    2026Q2-stage3-evaluation.md              ← Atomic: Stage 3実用性評価
    
  logs/                                      ← サイクル過程記録（凍結）
    2026Q2-signal-exploration.log.md         ← 作業ログ（旧WIP-progress.md）
    
  references/                                ← 不変参照資料
    hypothesis-space.md
    ideation-report.md
    ideation-catalog.parquet
    polygon-data-reference.md
```

### 各要素の役割と根拠

| 要素 | 役割 | 根拠 | 凍結/Evergreen |
|------|------|------|---------------|
| README.md | 次のサイクルの入口 | Diátaxis Tutorial + DSR Plan | Evergreen |
| hypotheses.parquet | 全仮説の累積記録 | Cookiecutter-DS processed + 棚卸し#1,#2解決 | 累積（追記のみ） |
| executions.parquet | 全実行結果の累積記録 | Cookiecutter-DS processed + 棚卸し#3解決 | 累積（追記のみ） |
| findings/ MOC | サイクル成果の全体像 | Obsidian MOC + DSR Reflect | 凍結 |
| findings/ Atomic | 個別の問いへの回答 | IMRaD + Obsidian Atomic Notes | 凍結 |
| logs/ | 作業過程の記録 | Lab Notebook原則 + 棚卸し#4解決 | 凍結 |
| references/ | サイクル横断の参照資料 | Cookiecutter-DS | 不変（新仮説追加時のみ更新） |
| ADR-013更新 | 方法論への教訓還元 | ADR + DSR Reflect→Plan + 棚卸し#5解決 | 進化 |

### 設計原則

| 原則 | 出典 | 適用 |
|------|------|------|
| 累積のみ、削除しない | DSR | hypotheses/executions.parquetは追記のみ |
| 1文書1問い | IMRaD | findings/の各Atomic Note |
| 成果と過程の分離 | Lab Notebook | findings/ vs logs/ |
| 入口を明確にする | Diátaxis Tutorial | README.md |
| リンクで全体像を提供 | Obsidian MOC | findings/のMOCからAtomic Notesへ |
| 方法論は独立文書で進化 | ADR | docs/adr/013 |

### 命名規約

- **サイクル名**: `{年}{四半期}-{内容の英語要約}` (例: 2026Q2-signal-exploration)
- **findings/**: `{サイクル名}.md`（MOC）, `{サイクル名}-{トピック}.md`（Atomic）
- **logs/**: `{サイクル名}.log.md`
- **Parquet**: 内容を表す名詞（hypotheses, executions）

### 既存ファイルの移行

| 現在のファイル | 移行先 | 操作 |
|--------------|--------|------|
| final_evaluation.md | findings/2026Q2-methodology-evaluation.md | 移動+Discussion追記 |
| stage1_stage2_report.md | findings/2026Q2-stage1-stage2-results.md | 移動 |
| stage3_evaluation.md | findings/2026Q2-stage3-evaluation.md | 移動 |
| WIP-progress.md | logs/2026Q2-signal-exploration.log.md | 移動 |
| hypothesis_space.md | references/hypothesis-space.md | 移動 |
| ideation_report.md | references/ideation-report.md | 移動 |
| ideation_catalog.parquet | references/ideation-catalog.parquet | 移動 |
| polygon-data-reference.md | references/polygon-data-reference.md | 移動 |
| signal_ideas.csv | executions.parquetに統合 | 変換後削除 |
| round2_results.csv | executions.parquetに統合 | 変換後削除 |
| stage2_results.csv | executions.parquetに統合 | 変換後削除 |
| signal_ideas.csv.bak | 削除 | 不要 |
| research-storage-design.md | references/research-storage-design.md | 移動（この文書自体） |

## ユーザー要件（確認済み）

| 要件 | 対応 |
|------|------|
| 研究は継続する（ファネル再実行+実運用FB+新アプローチ） | cycle列で世代管理、README.mdで入口提供 |
| 今すぐ次Cycleではない。マージ→整理→実運用が先 | 整理完了後にマージ可能な状態にする |
| 「前回何を試して何がダメだったか」をクエリしたい | hypotheses/executions.parquetでDuckDBクエリ可能 |
| 実運用成績と研究データの比較 | executions.parquetとDuckDB tradesテーブルをcycle列+signal_idで接続 |
| 判断経緯を残したい | findings/ MOCのDiscussionセクション |

## 参考文献

- Hevner, A.R. et al. (2004). "Design Science in Information Systems Research." MIS Quarterly, 28(1), 75-105.
- Lincoln, Y.S. & Guba, E.G. (1985). Naturalistic Inquiry. Sage.
- Conklin, J. & Begeman, M.L. (1988). "gIBIS: A Hypertext Tool for Exploratory Policy Discussion." ACM TOIS, 6(4), 303-331.
- Procida, D. "Diátaxis." https://diataxis.fr/
- Nygard, M. (2011). "Documenting Architecture Decisions." https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
- Matuschak, A. "Evergreen Notes." https://notes.andymatuschak.org/Evergreen_notes
- Cookiecutter Data Science. https://cookiecutter-data-science.drivendata.org/
