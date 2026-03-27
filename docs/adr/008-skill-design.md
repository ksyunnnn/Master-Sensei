# ADR-008: Skill設計とHook/CLAUDE.mdの責務分担

Status: accepted
Date: 2026-03-27

## Context

ADR-007で設計したトリガールール（SessionStart Hook → CLAUDE.md行動指針）の実効性を検証したところ、以下の問題が判明した:

1. Hook出力は「情報」としてコンテキストに注入されるが、Claudeが自発的にアクションを起こす強制力がない
2. 5つのトリガーのうち、緊急度が低いもの（stale知見検証、レジーム更新）を毎セッション自動化する必要がない
3. ユーザー起点のワークフローに適した仕掛け（Claude Code Skills）が未活用

同時に、session_start.pyが`src/db.py`の`SenseiDB`メソッドと同じSQLを直接書いており、DRY違反が存在した。Skillに同様のSQLを埋め込むと3重の重複になり、スキーマ変更時の冪等性が壊れる。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A: 全トリガーをHook自動化 | 漏れなし | 毎セッション強制、柔軟性低 | 不採用 |
| B: CLAUDE.md文言強化のみ | 実装変更ゼロ | 強制力弱、実効性不明 | 不採用 |
| C: 緊急度で自動/手動を分離 | 適切な粒度、柔軟 | Hook+Skill両方の保守 | 採用 |

## Decision

> トリガーを緊急度で分類し、自動（Hook）とユーザー起点（Skill）に分離する。
> SQLクエリは`src/db.py`のSenseiDBにのみ書き、Hook・Skillでは`SenseiDB`メソッドを使用する。

### 責務分担

| 機構 | 責務 | 例 |
|------|------|---|
| SessionStart Hook | 状態検出 + 緊急事項のアクション指示 | `[ACTION] 予測#1が期限切れ → resolve_predictionを実行せよ` |
| CLAUDE.md | `[ACTION]`出力時の行動ルール、会話中の行動指針 | 「`[ACTION]`が出たら確認なしに実行開始」 |
| Skills | ユーザー起点の定型ワークフロー | `/verify-knowledge`, `/update-regime` |
| Stop Hook | セッション終了前の最終チェック | condition.md更新確認、期限切れ予測チェック |

### トリガー分類

| トリガー | 機構 | 理由 |
|---------|------|------|
| 期限切れ予測 → 解決 | Hook（自動） | 期限あり、見逃すとBrier計測に穴 |
| エントリー分析→予測起草 | CLAUDE.md（行動ルール） | 会話中に発生、Hook検出不能 |
| stale知見 → 検証 | Skill（`/verify-knowledge`） | バッチ作業、ユーザーが時間のあるとき |
| データ古い → 更新 | Skill（`/update-regime`） | ユーザーが任意のタイミングで |
| セッション終了前チェック | Stop Hook（自動） | 既に機能している |

### SQLの所有権ルール

Hook・Skillは`SenseiDB`のメソッドを呼び出す。直接SQLを書かない。

## Rationale

- Claude Code公式: Hook出力はコンテキスト（情報）として注入される。命令ではない。CLAUDE.mdが行動指示の正規の場所
- Claude Code公式: Skillsはユーザーが`/name`で呼び出す定型ワークフロー。`SenseiDB`の使用を指示することでDRYを維持
- 冪等性: SQLの唯一の所有者を`db.py`にすることで、スキーマ変更の影響範囲を1ファイルに限定

## Consequences

- CLAUDE.md: トリガールール更新 + SQLの所有権ルール追記
- session_start.py: 直接SQL → SenseiDB呼び出しにリファクタリング
- `.claude/skills/verify-knowledge/SKILL.md`: 新規作成
- `.claude/skills/update-regime/SKILL.md`: 新規作成
- 見直しトリガー: Skill数が5を超えたとき、Hook/Skill/CLAUDE.mdの責務境界を再評価
