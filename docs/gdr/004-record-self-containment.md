# GDR-004: 永続記録の自己完結原則

**Status**: 採用 (Accepted) — 2026-07-01
**関連**: GDR-003（セッション間 状態管理の再設計）で外部トラッカーへ移行した結果、issue 本文に会話依存の記述が混入する問題が顕在化したことを受けて策定。

---

## Context

永続化された記録（トラッカー issue・commit・ADR/GDR・knowledge・doc・コード注釈）に、それを書いた会話の中でしか参照先が解決しない指示語が混入すると、後で読む者（未来の自分を含む）が意味を復元できない。

実測された違反例（2026-07-01 時点の GitHub Project #2）: 「次回セッションで /sync-saxo」「6/29 積み残し」「6/25→6/29 のギャップで」等、参照先が会話にしか存在しない issue が複数。モデル自身が記録執筆時にこの規律を自発適用できていない実証。

## Research

タグ: 〔言〕言語学・哲学 ／ 〔認〕認知科学 ／ 〔工〕工学的先例

- **永遠文 vs 機会文**〔言〕 — Quine『Word and Object』(1960)。機会文は「occasion により真偽が変わる」、永遠文は「once for all 真偽が定まり、話者と時をまたいで一定」。機会文を永遠文に変える標準手段 = 時間・場所の指示詞を絶対日付・地名で置換する。これが本原則の目標状態そのもの。
- **character vs content / 純粋指示詞**〔言〕 — Kaplan『Demonstratives』(1989)。指示詞は「character（文脈→内容の写像規則）」だけを保存し、文脈が失われると内容を生まない。重要な刃: `today` `now` `recently` は**純粋指示詞**で、参照先は発話時。→ 「絶対日付は可」は「アンカーされた絶対日付のみ可」を意味し、soft な時間指示詞（「最近」「現在」）も禁止対象。
- **deixis / Origo**〔言〕 — Bühler『Sprachtheorie』(1934), Levinson『Pragmatics』(1983)。指示詞は発話の Origo（会話・セッションという時空中心）に対してのみ解決する。後の読者はその Origo を占めない = 失敗の理論的核。
- **知の呪い（curse of knowledge）**〔認〕 — Camerer/Loewenstein/Weber (1989) が命名、Pinker『The Sense of Style』(2014) が悪文の主因として writing に適用。会話内にいる書き手は「読者が持たない文脈」を再構成できず、指示詞の未解決に気づけない。対処 = 文脈を共有しない読者でテストする。
- **ADR の supersession**〔工〕 — Nygard「Documenting Architecture Decisions」(2011)。ADR は Context/Decision/Consequences を単体で持ち、変更は編集でなく新 ADR が旧を supersede。過去状態が安全なのは過去形だからでなく、参照先が ID/リンクで**名指しされている**から。
- **commit の what & why**〔工〕 — cbeams「How to Write a Git Commit Message」。commit は年月後に文脈ゼロで読まれる典型。why を自己完結で説明し、周囲の会話に依存しない。
- **原子ノート**〔工〕 — Ahrens『How to Take Smart Notes』(2017), Luhmann Zettelkasten。1ノート=1アイデアを、文脈を失った未来の読者が単体で理解できるよう書く。
- **低コンテキスト / SoT**〔工〕 — GitLab Handbook。時間・空間で隔たった読者のため、必要な文脈をすべて書き下す。

## Options

配置手法の比較（「記録執筆時のみ必要な間欠ルール」を、複数媒体にまたがる執筆の瞬間に確実に効かせる、という要件で評価）。

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| CLAUDE.md に1行トリガー + checklist doc | pre-composition・全媒体・常時コスト最小・既存 checklist パターン（code-review-checklist / bias-audit-checklist）と一致 | model-recognition 依存（MEDIUM） | **採用** |
| ルール全文を CLAUDE.md に @import で常時ロード | 確実にロード | 間欠ルールに always-on 注意予算を恒久消費＝過剰。公式も「CLAUDE.md は薄く」 | 不採用 |
| `.claude/rules/` の paths スコープ | 該当コードを触る時だけロード | Read 発火のみ。新規 doc の Write・gh/git/DB 書き込みで発火せず、コード局所性のない記録執筆に噛み合わない | 不採用 |
| skill | 呼ばれた時だけロード | 自動発火なし・手動 invoke 前提＝忘れる問題を解決しない | 不採用 |
| PreToolUse hook（執筆時強制） | git/gh に deterministic | 公式仕様上 hook は事後発火（本文が書かれた後）＝pre-composition 不可。`additionalContext` は PreToolUse で公式未記載 | 現時点で不採用（将来オプション） |

## Decision

> 永続化するあらゆる記録は、それを書いた会話を見ていない読者が単体で読めること（= 記録内のすべての語の参照先が記録内で解決する）。判定基準は `docs/record-writing-checklist.md`。
>
> 強制手段は「CLAUDE.md Rules の1行トリガー + 上記 checklist（執筆時オンデマンド）」。禁止は指示詞であって時間的内容ではない（絶対日付・ID・リンク・アンカーされた過去状態は可）。適用は永続記録のみで、揮発的な会話・CLAUDE.md スタンス節は対象外。
>
> hook（PreToolUse・git/gh）は現時点で不採用。

## Charter Impact

- CLAUDE.md「Rules」に1行トリガーを追加。
- 既存 checklist パターン（ADR-022 の code-review-checklist、bias-audit-checklist）と同列の運用。
- 新規 ADR は不要（成長メカニズムの運用ルールであり、ソフトウェア構造の変更ではない）。

## Consequences

- **反映先**: `docs/record-writing-checklist.md`（新設）／ CLAUDE.md Rules（1行）／ 本 GDR。
- **トレードオフ**: model-recognition 依存のため、モデルが「記録を書いている」と認識しそこねると発火しない。常時強制の確実性は hook に劣るが、pre-composition の予防力と摩擦ゼロを優先した。
- **見直しトリガー**: このトリガーを入れても issue/commit への指示詞混入が継続して観測されたら、hook（PreToolUse・`git commit`/`gh project`/`gh issue`）の追加を再検討する。
