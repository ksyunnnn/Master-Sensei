# ADR-005: Grading — Full MCQ with objective scoring

- Status: proposed
- Date: 2026-04-17
- Supersedes: ADR-003

## Context and Problem Statement

v0.1 で採用した self-rating + rubric reveal 方式 (ADR-003) について、初回試用後にユーザーから「自己判断が不安」というフィードバックがあった。attempt 蓄積前のフィードバックではあるが、心理的障壁による学習継続リスクを重視し、採点方式を再検討した。

同時に、質問ファイル形式を Markdown (ADR-002) から純 YAML に移行し、構造化・バリデーションを強化する。

## Decision Drivers

- 採点の客観性 (self-grading の心理的不安を解消)
- Stage 1-2 の概念理解には recognition レベルで十分 (PMC 2024: MCQ vs free recall で知識定着に有意差なし, F=3.23, p=0.08)
- セッション独立 (Claude / ネットワーク不要)
- 将来の grading method 混在に対応できるデータ設計

## Considered Options

Issue #3 で 5 案を比較検討:

- **A. 現状維持 (self-rating + rubric)**: 心理的障壁が残る
- **B. 完全 MCQ 化**: 客観採点、recognition テスト
- **C. LLM grading**: 最高精度だがネットワーク依存・コスト
- **D. Keyword matching**: 日本語表記揺れに脆弱
- **E. ハイブリッド (recall -> MCQ 確認)**: UX が複雑

追加で「構造化 self-rating (rubric チェックリスト化)」も検討。recall を維持しつつ採点を構造化できるが、self-grading の不安自体は残る。

## Decision Outcome

**B. 完全 MCQ 化を採用。**

### 1. 採点方式

- 全問 MCQ (4 択)。正解/不正解の客観判定
- outcome: 正解 -> `correct`、不正解 -> `wrong`
- `partial` は MCQ では発生しない (Leitner scheduler は引き続き partial を受け付けるが、MCQ フローでは使わない)
- self_rating は記録しない (NULL)

### 2. DB 設計: grading_method 列

`learning_attempts` に `grading_method` 列を追加:

```
grading_method VARCHAR NOT NULL DEFAULT 'self'
-- 値: 'self' | 'mcq_auto' | 'llm'
```

- `self_rating` は NULL 許容に変更
- v0.1 既存データ: `grading_method='self'`, `self_rating='A'/'B'/'C'`
- v0.2 MCQ: `grading_method='mcq_auto'`, `self_rating=NULL`
- 将来 LLM: `grading_method='llm'`, `self_rating=NULL`

### 3. 質問ファイル: 純 YAML 化

ADR-002 の Markdown + YAML front matter 形式から純 YAML (.yml) に移行:

- 全フィールドがスキーマ検証可能
- loader.py が `yaml.safe_load()` ベースに簡素化
- Markdown セクション解析が不要に
- ADR-002 の要件 (Git diff / 自動同期) は維持

### 4. Distractor 設計基準

- 各問最低 1 つは「よくある誤解」ベースの plausible distractor
- 正答率 >90% の問題は distractor が甘い -> `/learn-status` で検出し改修

### Consequences

- 良い面: 客観採点で心理的障壁解消、grading_method で将来の混在運用に対応、YAML 化でバリデーション強化
- 悪い面: recall (生成) -> recognition に認知要求が低下、partial が消え Leitner が二値判定に
- 認識済みリスク: distractor の質が学習効果を左右する (雑な distractor = 消去法で解ける = 学習効果ゼロ)

## Re-evaluation Triggers

| 条件 | アクション |
|------|----------|
| Stage 1 mastery 50% 到達 | `/learn-status` で正答率と理解度乖離を検証 |
| 全問正答率 >90% | distractor が甘い -> 改修 |
| Stage 3-4 到達時 | recall + LLM grading の検討 (新 ADR) |

## Bias Audit (2026-04-17)

### Premortem (要対策 1 件)

1. **MCQ distractor が甘く「分かったつもり」蓄積** — 可能性: 高, 影響: 大 -> distractor 設計基準を本 ADR に明記、`/learn-status` で正答率監視
2. **Stage 3-4 で recognition != recall ギャップ** — 可能性: 中, 影響: 大 -> 再評価トリガー設定済み
3. **Claude の実装容易性バイアス** — 可能性: 中, 影響: 中 -> 判断根拠は学習効果のみで記述
4. **attempt 0 でのフィードバックに基づく判断** — 可能性: 中, 影響: 大 -> 再評価トリガー設定済み
5. **研究の確認バイアス** — 可能性: 中, 影響: 中 -> p=0.08 は marginally significant で recall 側に傾いている点を honest に記載

### Kahneman 12 問: 3 件 (実行可)

## References

- [VSAQ vs MCQ 比較 (PMC 2024)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11684041/)
- [Retrieval Practice Task Differences (Springer 2020)](https://link.springer.com/article/10.1007/s11251-020-09526-1)
- [Anki cohort study medical school (PMC 2023)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10403443/)
- ADR-003 (superseded)
- Issue #3 (議論経緯)
