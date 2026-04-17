# ADR-023: 学習ドリルシステム設計

Status: accepted
Date: 2026-04-16 (initial) / 2026-04-17 updated (independent architecture)

## Revision history

- 2026-04-16 initial: `src/learning/` + `sensei.duckdb` 共用で実装
- 2026-04-17 refactor: ユーザー要求「完全独立」を受け `learning/` top-level + `learning/data/drill.duckdb` 独立 DB に移動。エントリポイント `drill.py` のみ root。`src.db` 依存を `learning/timeutil.py` として切り出し

## Context

ユーザーは体系的な金融・投資教育の学習経験なし。Master Sensei のレポートを完全理解するには、Stage 1（金融・統計基礎）から Stage 4（Master Sensei 独自概念）まで、約 50-100 用語のスキーマ構築が必要。診断セッション (2026-04-16) で A=2, B=5, C=11 が確認され、foundational gap の深さが定量化された。

ユーザー要件:
- セッション依存でない自律運用（Claude に毎回依頼しない）
- 解説 + クイズの pair が continuable（続けやすい）
- Python ベースの CLI で OK（SE 素養あり）
- 公文式的ドリル（反復・漸進・即フィードバック）
- Claude 側は結果を定期レビューしてカリキュラム調整

学習科学リサーチ (2026-04-16 実施) で以下が確認:
- FSRS (2022+) が SM-2 を log loss で超える (Expertium benchmark)
- ただし FSRS は 17 parameter の ML training が必要、MVP には過剰
- Leitner 5-box system は 50-200 問規模で well-validated (PNAS 2019, et al.)
- Free recall > MCQ で retention/transfer 強化 (Instructional Science 2020)
- "Any feedback > no feedback" — 正解時も explanation 表示必須

## Options

### Scheduling Algorithm

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| **Leitner 5-box** | 実装 30 行、well-validated、decisions deterministic | Fixed interval、performance adaptive でない | **採用 (MVP)** |
| FSRS-lite (default params, no training) | 理論的に優れる、3-component model | 17 params 必要、ユーザー data 少時に不安定 | 不採用 (200問超で再検討) |
| Anki 統合 | 既存ツール、ecosystem 大 | 別アプリで project isolation 失う、Python script と統合不能 | 不採用 |
| 自己実装 FSRS (full) | 最高性能 | 実装 500+ 行、ML training 必要 | 不採用 |

### 質問形式

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| Free recall + self-grading (rubric 表示) | 深い elaboration, transfer 強 | 自己採点バイアス | **採用 (主)** |
| MCQ (4択) | 機械採点可、短時間 | Elaboration 浅い、Dunning-Kruger 助長 | **採用 (補助)** |
| Application (レポート抜粋読解) | Bloom Apply レベル、実用直結 | 作成コスト高 | **採用 (Stage 2以降)** |

Dunning-Kruger バイアスが diagnostic で低いことが確認済なので、self-grading は機能する。

### データ保存先

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| 独立 `learning/data/drill.duckdb` | 完全 isolation、配布や削除が容易、市場 DB とライフサイクル分離 | Claude 側 MCP 既定接続は sensei.duckdb のみ（別途パス指定で OK） | **採用 (2026-04-17 以降)** |
| `sensei.duckdb` に `learning_*` テーブル追加 | 単一 SoT、既存 backup 運用に乗る、DuckDB MCP 既定接続で即クエリ可 | concern 混在、市場データと学習データのライフサイクルが逆転、ユーザー要求「完全独立」に反する | **2026-04-17 撤回** |
| SQLite | 軽量 | DuckDB 統一から逸脱 | 不採用 |
| JSON/CSV | 依存ゼロ | SQL クエリ不可、スケール困難 | 不採用 |

### 質問バンク保管形式

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| Markdown ファイル → DB loader | 編集容易、diff レビュー可、git tracking | Load step 必要 | **採用** |
| DB 直書き | Load 不要 | 編集は SQL or script、diff なし | 不採用 |
| YAML | 構造化 easy | Human edit が Markdown より劣る | 不採用 |

## Decision

> **Leitner 5-box の drill CLI を `learning/` 配下に実装（完全独立アプリ）。質問は Markdown (`learning/data/questions/`) で保管し loader 経由で `learning/data/drill.duckdb` に取り込む。sensei.duckdb とは共有しない。エントリポイントのみ repo ルートの `drill.py`。Claude 側は `/learn-status` Skill で attempts を review しカリキュラムを調整する。**

## Rationale

### Leitner 採用の根拠

PNAS 2019 の Enhancing Human Learning via Spaced Repetition Optimization で確認された通り、fixed-interval (Leitner) でも distributed practice による向上は meta-analytically 確認されている。FSRS の優位は 1000+ cards の regime で顕著だが、50-200 問規模では noise に埋もれる。MVP のシンプルさ優先。

Box 間隔 (業界 de facto):
- Box 1: daily
- Box 2: 2 日後
- Box 3: 4 日後
- Box 4: 8 日後
- Box 5: 16 日後
- 正解 → 1 box 上昇（5 で頭打ち、mastered 判定）
- 誤答 → Box 1 にリセット

Mastered 判定: Box 5 で 2 回連続正解 → `mastered` ステータス、通常 rotation から除外（月 1 ランダム review）。

### Free recall + self-grading 採用の根拠

Instructional Science 2020 (Task Differences in Retrieval Practice) で、free recall の retention 優位が確認されている。機械採点困難な問題はあるが、rubric (模範解答の keyword セット) を答え入力後に表示 → ユーザーが自己評価 (A/B/C) する形式で対応。

Dunning-Kruger バイアス: 診断 (2026-04-16) で 17 用語のうち C=11 を正直に選んだ実績 → self-grading が機能する前提が成立。

### DB 独立の根拠 (2026-04-17 更新)

当初は sensei.duckdb に `learning_*` テーブルを相乗り。2026-04-17 にユーザー要求でアプリを完全独立化し、`learning/data/drill.duckdb` に分離。根拠:

- ライフサイクルが逆転: 市場 DB は毎日更新、学習 DB は attempts 追加のみ
- 外部配布・削除・リセットが容易 (drill.duckdb 単独削除で学習状態クリア)
- ADR-001 の「関心分離」原則と整合 (市場データと教育データは別 concern)
- トレードオフ: Claude の DuckDB MCP 既定接続は sensei.duckdb のみ。`/learn-status` Skill は明示パスで drill.duckdb に接続する

### Markdown → DB loader の根拠

ADR-008 (Skill design) の「Markdown + DB 二層運用」と整合。質問の追加・修正は git diff でレビュー可能にしつつ、runtime は DB の indexed クエリで高速化。

## Consequences

### 反映先

- `learning/` トップレベル独立パッケージ: `db.py` / `scheduler.py` / `loader.py` / `cli.py` / `timeutil.py`
- `learning/data/drill.duckdb` — 学習専用 DuckDB (初回起動時に作成)
- `learning/data/questions/stage_1/*.md` — 初期 10 問
- `learning/tests/test_learning.py` — scheduler / loader / db の単体テスト (22 件)
- `drill.py` — repo ルートのエントリポイント (3 行)
- `.claude/skills/learn-status/SKILL.md` — Claude 側のレビュー Skill
- `docs/curriculum.md` — Stage 設計と用語マッピング
- `sensei.duckdb` 側: `learning_*` テーブル drop 済 (2026-04-17)

### トレードオフ

- **受容**: Leitner は FSRS より最適性が低い → 200 問超で再検討
- **受容**: self-grading はバイアスリスクあり → Claude 定期レビューで外部 calibration
- **受容**: Markdown 編集後 loader 実行が手間 → 「loader 自動起動 on drill.py 起動」で吸収

### 将来の見直しトリガー

- 質問バンクが 200 問超 → FSRS 移行検討 (ADR-024 候補)
- Self-grading と Claude レビューの乖離が 20% 超 → MCQ 比率増加
- Mastery 判定後の忘却率 > 30% → Box 5 以降の long-term rotation 強化
- Stage 4 到達時 → application questions の比率見直し

## Reference

- [Enhancing Human Learning via Spaced Repetition Optimization (PNAS 2019)](https://www.pnas.org/doi/10.1073/pnas.1815156116)
- [FSRS vs SM-2 Benchmark (Expertium)](https://expertium.github.io/Benchmark.html)
- [Retrieval Practice Task Differences (Instructional Science 2020)](https://link.springer.com/article/10.1007/s11251-020-09526-1)
- [Leitner System (Wikipedia)](https://en.wikipedia.org/wiki/Leitner_system)
- ADR-001: Storage strategy
- ADR-008: Skill design
- ADR-009: Storage responsibility separation
