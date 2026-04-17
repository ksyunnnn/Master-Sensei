# ADR-002: Question bank — Markdown + loader

- Status: accepted
- Date: 2026-04-16

## Context and Problem Statement

質問マスターをどこに・どの形式で保管するか。編集頻度 (週 5-10 問追加想定)、バージョン管理 (git diff で review したい)、runtime 速度 (起動時ロード < 1 秒) のバランスが要件。

## Decision Drivers

- Markdown diff が git で clean に読める
- Claude が質問を追加 / 修正する際、特別ツールなしで触れる
- 起動時の load は 100 問程度で感じない速度
- 編集と実行の流れが 1 アクション (編集 → 起動 → 反映)

## Considered Options

- **Markdown + YAML front matter → DB loader**
- **DB 直書き** (Python スクリプト or SQL で INSERT)
- **YAML ファイル直接**
- **SQLite with CSV import**

## Decision Outcome

**Markdown + YAML front matter を採用**し、起動時に `learning/data/questions/**/*.md` を DuckDB に auto-upsert する。

Runtime では DB の indexed クエリ、編集時は Markdown の可読性、の両立。git diff は Markdown で自然に読める。

### Consequences

- 良い面: Claude がエディタで直接質問を書ける、diff review 可能、起動時 auto-sync
- 悪い面: 解説 (Explanation) に長文を書くと Markdown が膨らむ → 1 問 1 ファイル分割で対処
- 見直しトリガー: 質問バンクが 500 問超えた時、起動時 load が 1 秒を超えるなら DB 直書きモードへ段階移行

## Pros and Cons of the Options

### Markdown + YAML front matter
- Pros: 人間可読、git diff clean、Claude で直接編集可
- Cons: 起動時 load step 必要、パーサの保守

### DB 直書き
- Pros: Load 不要、起動高速
- Cons: 編集に SQL or script 必要、diff が binary 風になる

### YAML ファイル直接
- Pros: 構造化が強い
- Cons: 解説 (長文) の記述性が Markdown より劣る

### SQLite + CSV import
- Pros: インポートツール充実
- Cons: DuckDB 統一から逸脱、質問解説の改行が CSV で扱いにくい

## Format

```markdown
---
id: Q-001
stage: 1
category: basic
term: ETF
type: recall | mcq | application
difficulty: 1
prereqs: []
---

## Prompt
...

## Rubric          (recall 必須、mcq は任意)
- keyword1

## Choices         (mcq 必須)
A. ...
B. ...

## Correct         (mcq 必須)
A

## Explanation
...
```

## References

- ADR-001 (scheduler、Markdown の metadata で difficulty を渡す必要)
- 一般論: YAML front matter は Jekyll / Hugo / Astro など静的サイトで標準
