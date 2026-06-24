# GDR-002: condition.md ハンドオフの肥大化対策（アーカイブ分割 + バナー構造統一）

Status: accepted
Date: 2026-06-25

## Context

`docs/condition.md`（「現在地」＝セッション間ハンドオフ文書）が肥大化し、運用上の機能不全が出た。

- session 57 末時点で **2395行 / 250KB / 約30k トークン**、`##` セクション 51個（session 1〜51 + 4月期のレガシー構造）が append-only で累積。
- **Read ツールの 25k トークン上限を超え、1回の Read で全文を開けない**（session 58 で実測）。オンデマンド参照のハンドオフ文書なのに「読めない」＝機能の一部喪失。
- **二重管理**: 最新 session 52〜57 は冒頭バナー（`Last updated:` 行）に prose で圧縮、session 51 以前は `##` セクション。とくに session 57 の詳細（11項目）が `Last updated:` 行に直書きされ、**ヘッダ1行だけで ~15.8k トークン**を占有していた。
- 短期トレードのハンドオフでは直近2週間より古い handoff はほぼ参照されない（情報の時間価値が急減する性質）。

## Research

Claude Code 公式ドキュメント（[memory.md](https://code.claude.com/docs/en/memory.md)）を確認。

- **CLAUDE.md は 200行以下推奨**。超えるとコンテキスト消費増・指示遵守率低下。長文の根本対処は **分割（path-scoped rules / 別ファイル）**で、`@import` は「組織化であってコンテキスト削減ではない」と明言。
- **状態・進捗ログは CLAUDE.md でも auto-memory でもなく、git 管理の `.md` か DB に置く**のが公式の設計原則（CLAUDE.md=不変の指示、auto-memory=Claude の発見）。
- → condition.md を git 管理 `.md` に置く現行設計は公式と合致。**かつ SessionStart フックは condition.md 本体を注入せず DB 由来の状態サマリのみ注入**＝毎セッションのコンテキスト肥大は元々回避されている。残る問題は「オンデマンド参照時の可読性」と「append-only の無制限成長」のみ。

公式は状態ファイルのサイズ上限を直接規定しないが、「長い→分割」原則をハンドオフ文書にも適用するのが妥当と判断。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A. 現状維持 | 作業ゼロ | Read 不能・成長無制限が継続 | 不採用 |
| B. アーカイブ分割（古い handoff を別ファイルへ退避） | 1回 Read 可・履歴は完全保全・純粋な「移動」で内容無改変 | アーカイブ参照の一手間 | **採用** |
| C. B + バナーの session 57 詳細を `##` セクションに降格し構造統一 | 二重管理解消・他セッションと一貫 | 移動操作がやや繊細 | **採用** |
| D. CLAUDE.md の手順記述を skill 参照に圧縮 | 公式の「手順→skill」に合致 | Saxo token/keepalive/サイジング手順は実損から学んだ規律（K番号・ADR参照）を凍結。剥がすと知見喪失リスク | **不採用（今回見送り）** |
| E. 古い handoff を要約圧縮 | サイズ最小 | 内容の不可逆な欠落・後知恵での歪曲リスク | 不採用 |

## Decision

> **condition.md は「直近ウィンドウ + アーカイブ退避」の2ファイル運用とする。**
> 1. **アーカイブ分割**: session 46 以前の handoff と 4月期のレガシー構造を `docs/condition-archive.md` へ退避（純粋な行移動・内容無改変）。condition.md には末尾にアーカイブ参照リンクを置く。
> 2. **直近ウィンドウ**: condition.md は「最優先バナー → `Last updated:` 短縮スタンプ → `## Session 57` 以降の直近セクション（57 + 51〜47）」を保持。
> 3. **バナー構造統一**: 肥大化した `Last updated:` 行の session 詳細を `## Session NN Handoff` セクションへ降格し、`Last updated:` は日付スタンプ + 参照ポインタの1行に純化（Stop フックの鮮度判定 `Last updated: YYYY-MM-DD` 正規表現は維持）。
> 4. **次セッション以降の運用ルール**: 各セッションは（a）最優先バナーを更新（b）当該セッションを `## Session NN Handoff` セクションとして追記。**condition.md が再び ~20k トークン / 1回 Read 上限に近づいたら、古い側を condition-archive.md へ移す**（恒久的な append-only を禁止）。要約圧縮でなく移動で行い、内容は無改変とする。

実施: session 58（2026-06-25）。condition.md 2395行→143行（~21k tok、1回 Read 可）、condition-archive.md 2269行を新設。セクション保全検算 = 元 51 セクション ＝ main 残置 5（S51-47）+ archive 46。session 57 はバナー prose から新規セクション化。

## Charter Impact

- Charter のメカニズム本体には影響なし（計測体系・自己評価は不変）。
- CLAUDE.md「Structure」表の condition.md の役割（現在地）は不変。運用ルール（成長に伴う分割）を本 GDR で規定。
- 関連ADR: ADR-007/008（フックによる状態注入）、ADR-001（データ配置）。実装判断は伴わず（フック・スキーマ不変）、ゆえに新規 ADR 不要。

## Consequences

- 反映先: `docs/condition.md`（縮約）、`docs/condition-archive.md`（新設）、本 GDR。
- トレードオフ: 古い handoff 参照に1ホップ増。短期トレード文脈では古い handoff の参照頻度が低く許容。
- 見直しトリガー: condition.md が再び 1回 Read 上限（~22k tok）に近づいたら追加退避。退避は「移動」に限り「要約圧縮」を禁止（後知恵バイアス・情報欠落の防止）。
- フック互換: Stop フックの `Last updated:` 鮮度判定は維持（session 58 で dry-run 検証済）。SessionStart は condition.md を読まないため影響なし。
