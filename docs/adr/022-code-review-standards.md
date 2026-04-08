# ADR-022: 統計・金融コードのレビュー基準導入

Status: accepted
Date: 2026-04-02

## Context

research_utils.py（ADR-013のファネル実装）の初回レビューで、以下のバグが検出された:

| # | 問題 | 深刻度 | 原因 |
|---|------|--------|------|
| 1 | 並替テストp値が反保守的（p=0.0を返しうる） | Critical | 統計的正確性の確認不足 |
| 2 | record_result TOCTOU競合 + カラム不一致 | Critical | 並行処理のエッジケース |
| 3 | 全True信号のシャッフルが無意味（no-op） | High | ドメイン知識の適用不足 |
| 4 | float 0/1がboolと誤判定される | High | 型判定の不正確さ |
| 5 | regime N整合性（事前チェックとscreen_signal内部チェックの乖離） | High | レイヤー間の整合性不足 |

これらは一般的なコーディングミスではなく、統計的正確性・金融データ処理・並行処理に特化した知識が必要な問題。再発防止にはドメイン固有のレビュー基準が必要。

調査した方法論:
- Phipson & Smyth (2010): 並替テストのp値計算
- BH法実装のよくある間違い（FDR vs FWER混同、ソート順序）
- バックテストの7つの大罪（look-ahead bias, survivorship bias等）
- 定量金融のアンチパターン（過適合、非定常性無視）

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A: ADRのみに記録 | 判断根拠が残る | 処方的ルールとして参照しにくい | 不採用 |
| B: チェックリスト文書のみ | 実行時に参照しやすい | 「なぜ」が失われる | 不採用 |
| C: ADR（根拠）+ チェックリスト（処方）の二段構成 | 根拠と実行の分離 | 2ファイル管理 | **採用** |

## Decision

> 1. `docs/code-review-checklist.md` を処方的ガイドラインとして作成する
> 2. CLAUDE.md の Rules セクションからチェックリストを参照する
> 3. チェックリストは統計的正確性・金融データ処理・並行処理の3領域に分類する
> 4. ADR（本文書）は導入根拠を記録する

## Rationale

- ADRは一時点の判断記録（immutable）。チェックリストは継続的に更新される処方的ルール
- CLAUDE.md からの参照により、セッション中にコードレビューが発生した際に自動で読み込まれる
- 既存の docs/ 構成（charter.md, api-constraints.md）と同じレイヤーに配置

## Consequences

- `docs/code-review-checklist.md` を新設
- CLAUDE.md に `@docs/code-review-checklist.md` 参照を追加
- research_utils.py で発見された5件は修正済み（本ADRと同セッション）
- 見直しトリガー: 新たなドメイン固有バグが発見された場合にチェックリストを拡充
