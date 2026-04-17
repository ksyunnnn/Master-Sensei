# ADR-003: Grading — Self-rating with rubric reveal

- Status: accepted
- Date: 2026-04-16

## Context and Problem Statement

Free recall 質問をどう採点するか。機械採点は日本語自由記述で困難、Claude に毎回採点させるとセッション依存になる。公文式の「自己採点 + 後でチェック」パターンとも整合する必要。

## Decision Drivers

- セッション独立 (Claude なしで完結)
- Free recall の retention 優位 (Instructional Science 2020) を活かす
- 自己採点バイアスのリスクを外部 calibration で吸収できる仕組み
- MCQ と統一 UI

## Considered Options

- **Self-rating (A/B/C) + rubric reveal**: 解答入力 → rubric (模範キーワード) 表示 → 自己評価
- **Keyword matching**: 解答に rubric の keyword が何個含まれるかで自動採点
- **LLM grading**: 毎回 Claude API を呼んで採点
- **Full MCQ only**: Free recall を諦めて全問選択式

## Decision Outcome

**Self-rating + rubric reveal を採用**。

根拠:
1. 事前の診断セッション (2026-04-16、17 用語を A/B/C で自己申告) でユーザーの Dunning-Kruger バイアスが低いと確認できた (C=11 を honest に選択)
2. Keyword matching は日本語の文体差 (「元本保証なし」vs「元本は保証されない」) で false negative を起こしやすい
3. LLM grading は外部 API 依存 + コスト + レイテンシで MVP に不適合
4. Full MCQ は elaboration 浅く、retention / transfer が free recall より劣る (Instructional Science 2020)

### Consequences

- 良い面: Claude 不在でも完結、即フィードバック、MCQ/recall の UI 統一
- 悪い面: self-rating バイアスは理論的に残る → `/learn-status` Skill で Claude が外部 calibration
- 見直しトリガー: `/learn-status` レビューで self-rating と Claude 判定の乖離が 20% を超えた場合、MCQ 比率を増やす or LLM grading ハイブリッドを検討

## Pros and Cons of the Options

### Self-rating + rubric reveal
- Pros: 実装シンプル、即時、独立性保持、診断で前提成立確認済み
- Cons: バイアスリスク (緩和策: 外部レビュー)

### Keyword matching
- Pros: 自動採点で objective
- Cons: 日本語の表記揺れに弱い、rubric メンテ負荷大

### LLM grading
- Pros: 最高精度
- Cons: コスト / レイテンシ / 外部依存、セッション独立性を損ねる

### Full MCQ
- Pros: 完全自動採点
- Cons: retention 低下、ユーザー負担軽減と引き換えに効果下がる

## User feedback (2026-04-17 試用後)

初回試用でユーザーから以下の feedback:
- 自由入力だと採点が不安 → v0.2 で「完全 MCQ」「LLM grading」「ハイブリッド」の再検討候補
- 日本語入力 + 操作キーの打ち鳴らしが面倒

これを受けて ADR-003 は **accepted のまま** (初期仕様として凍結)、次の改修は新規 ADR で supersede する。

## References

- [Retrieval Practice Task Differences (Ariel & Karpicke, Instructional Science 2020)](https://link.springer.com/article/10.1007/s11251-020-09526-1)
- Roediger & Karpicke 2006 — Testing effect meta-analysis
- ADR-001 (scheduler が A=correct / B=partial / C=wrong を受け取る)
