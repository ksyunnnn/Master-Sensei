# ADR-019: 日時供給の統一（JST明示取得）

Status: accepted
Date: 2026-04-02

## Context

Master Senseiシステム全体で`date.today()`（14箇所）と`datetime.now()`（2箇所）がシステムTZに暗黙依存していた。加えて、Claudeの会話コンテキストに現在時刻を供給する仕組みがなく、日時の誤認（「明日」と「今夜」の混同等）が発生した。

問題を3層に分解:
1. **Claudeへの日時供給**: SessionStartフックが状態は注入するが時刻を注入しない。会話中に時刻を知る手段がない
2. **Pythonコードの日時取得**: `date.today()`はシステムTZ依存。JST以外の環境で1日ズレる
3. **スキル間の不統一**: 5スキル中3つのみに時刻注入があり、2つ（update-regime, verify-knowledge）に欠落

### 「正しい時刻」の定義（本ADRで確立）

- 基準: JST（全用途共通）
- 精度: 分単位。不明な場合は「4/2未明」のように幅で表現
- 表記: JST表記（米国時間補足）。例: 「今夜22:30 JST（米国朝9:30 ET）」
- 供給条件: コンポーネント動作時点のJST日時が明示的に取得・表示・検証されていること

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A: 現行維持（`date.today()`） | 変更なし | システムTZ依存、Claudeに時刻供給なし | 不採用 |
| B: `now_jst()`/`today_jst()`に統一 | TZ非依存、単一ソース、性能同等（0.17μs/call） | 全箇所の修正が必要 | **採用** |
| C: 環境変数でTZ強制（`TZ=Asia/Tokyo`） | コード変更少ない | プロセス全体のTZを変更、副作用リスク | 不採用 |

## Decision

> 1. `src/db.py`に`now_jst()`（datetime, JST aware）と`today_jst()`（date, JSTの今日）を定義し、全Pythonコードで使用する
> 2. `date.today()`および`datetime.now()`の直接使用を禁止する（CLAUDE.md Rulesに明記）
> 3. SessionStartフックの出力に「現在: YYYY-MM-DD HH:MM JST」を追加する
> 4. 全5スキルのSKILL.mdにタイムゾーン注入セクションを設ける
> 5. Claudeは日時を発言する前に`TZ=Asia/Tokyo date`で現在時刻を確認する

## Rationale

- `datetime.now(tz=JST)`はシステムTZに関わらず常にJSTを返す（Python公式ドキュメント）
- ベンチマークで`date.today()`（0.44μs）より`datetime.now(tz=JST)`（0.17μs）が高速であり、性能上のトレードオフなし
- `src/db.py`にJST定数が既に存在し、ヘルパーの配置先として自然
- SessionStartへの時刻注入は1行追加で最大のインパクト（全セッションで時刻認識が改善）

## Consequences

- 反映先: src/db.py, cache_manager.py, update_data.py, assess_regime.py, hooks 2ファイル, SKILL.md 5ファイル, tests/test_db.py, CLAUDE.md
- 修正規模: 16箇所の`date.today()`/`datetime.now()`を置換、テスト2件追加（152テスト全パス）
- トレードオフ: `src.db`への依存が増える（cache_manager.py, update_data.py等）。ただし`JST`定数は既にdb.pyからimportされる慣行があり、追加的な結合は最小限
- 見直しトリガー: 海外サーバーでの実行が必要になった場合、UTC/ET変換ロジックの追加を検討
