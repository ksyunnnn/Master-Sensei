# ADR-035: live 読み取り用 MCP サーバ（型付き Saxo/realtime アクセサ）

Status: accepted
Date: 2026-07-08

> **ADR運用ルール（Nygard慣行）**: accepted な ADR の substance は後から書き換えない（immutable）。結論を変える必要が出たら新しい ADR を起こして古い方を supersede する。

## Context

Claude が API 由来の問い（残高・建玉・注文・約定履歴・含み損益 等）に答える際、その場で ad-hoc python を書き、ファイルパス・DataFrame カラム名・dataclass アクセサ名を**推測して外し**、定義を読み直す往復が繰り返し発生している。実例:

- **2026-07-06**: `AccountBalance.cash_balance`（非存在、正は `spending_power`）/ `OpenOrder.instrument`（非存在、正は `symbol`）をハンドライトして `AttributeError`。
- **2026-07-08**: 口座状況取得で執行事実層 parquet のパス（`data/parquet/account_transactions.parquet` 誤 → `data/parquet/account/transactions.parquet` 正）とカラム（`price`→`price_per_unit`、`symbol`→`instrument`）を連続で誤ってから正解に到達。

いずれも **API 応答遅延ではなく read 経路が定型化されていないこと**が原因。「SoT=API」（ADR-030）は "API 応答遅延以外に時間がかからない" 前提でのみ成立する。

### 既存資産の棚卸し（2026-07-08 調査）

- 意味的アクセサ層は**既に完備**: `src/saxo_client.py`（`get_all_account_balances()→AccountBalance`、`get_live_positions()→LivePosition`、`get_open_orders()→OpenOrder`、`get_trade_cost()→TradeCost`、`get_trade_reports()`/`get_bookings()`）、`src/db.py`（`SenseiDB` 30+ メソッド）、`src/realtime.py`（`fetch_realtime_quote()→RealtimeQuote`）。**正しい入口は存在するのに Claude が reach しない**のが問題の本質。
- **duckdb MCP が既に稼働**（`.mcp.json`、`mcp-server-motherduck --db-path ./data/sensei.duckdb --read-only`）。蓄積層（events/predictions/knowledge/regime/trades）の SQL 照会はここでカバー済み。
- **fumble 源は2つに限定**: (a) 執行事実層 parquet のパス/カラム（既存 duckdb MCP に VIEW を張れば名前で照会可）、(b) **live Saxo 読み取り（残高/建玉/注文/cost）と realtime quote はどの MCP にも無い**（API 呼び出しで duckdb ファイルに入っていない）＝ここが主 fumble 源。
- 地雷: `docs/api/saxo/README.md` が**存在しないアクセサメソッド**（`get_spending_power()` 等）を宣伝しており、ドキュメント自身が fumble を誘発している（ADR-026 違反の再生産源）。

### 手法調査の結論

「Claude がアクセサ名・パス・カラムを推測して外す」を**構造的に根絶できるのは MCP サーバ（JSON schema 強制）のみ**。スキル / フック / CLAUDE.md prose は "should" であって "must" にならない（本 repo は既に prose で誘導しているが効いていない）。permissions deny は ad-hoc を塞いで正道へ誘導する補助。**受益者を Claude（エージェント）に決定**したため（Issue #12）、人間が呼べない MCP の短所は無効化され、手法は MCP に一意に定まる。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A. 最小整備のみ（doc-drift 修正・parquet VIEW・ad-hoc deny） | 低コスト・即効・既存 duckdb MCP を活用・受益者非依存 | live Saxo 読み取りが未解決のまま | **補完として採用**（単独では主目的を満たさず、主軸には不採用） |
| B. 薄い統一 CLI（`sensei status/balance/...`） | 人間とエージェント両方が使える | 型強制なし（stdout 依存）。受益者=Claude なら人間向け価値が主目的外 | 不採用（今回。将来人間も欲したら別 ADR で追加可） |
| C. カスタム MCP サーバ（live 読み取りを型付きツール化） | schema 強制で推測が物理的に不可能・エージェントネイティブ・既存アクセサをラップ | サーバ保守・session ごとの context コスト・token/DB ロック設計が要る | **採用（主軸）** |
| D. CLAUDE.md / prose 強化 | ゼロコスト | 既に効いていない（長文は文脈から追い出され must にならない） | 不採用 |

## Decision

> **live 読み取り専用のカスタム MCP サーバを新設**し、既存 `SaxoClient` / `realtime` を型付き MCP ツールでラップする。あわせて受益者非依存の最小整備（案A）も実施する。
>
> **スコープ**: duckdb ファイルに無い **live 読み取りに限定**する — 残高（`get_account_balances`）・建玉（`get_positions`）・未約定注文（`get_open_orders`）・往復コスト/break-even（`get_trade_cost`）・realtime quote（`get_realtime_quote`）。**蓄積層 SQL は既存 duckdb MCP の担当**とし重複させない。ツールは既存の意味的アクセサを呼び、返す dataclass を JSON（named fields）へ整形する。raw dict を返さない（ADR-026）。
>
> **並行性（DB ロック）**: MCP ツールは呼び出しごとに**短命の DuckDB 接続**を開閉する（既存 scripts / keepalive と同一規律＝アイドル中にロックを保持しない、ADR-025）。読み取りは既定 `read_only`（共有ロック、duckdb MCP と共存）。access token が失効していて on-demand refresh が要る時のみ、**短時間 read-write** に昇格して新 token を永続化し、直後に閉じる。`keepalive` は引き続き **refresh チェーンの backstop**（失効直前 roll でブラウザ再認証を稀にする）として併走する。両者とも「ロックを保持し続けない」ため単一 writer 制約下の競合窓は瞬間的で、`IOException`（ロック取得失敗）は指数バックオフで数回リトライして吸収する。
>
> **token 失効フォールバック**: refresh token 自体が失効していれば、ツールは構造化エラー `AUTH_REQUIRED` を返す。**MCP はブラウザ認証を起動しない**（人間のログインが要るため会話層で `saxo_oauth_init.py` を扱う、ADR-025）。Claude はこのエラーを受けて再認証フローへ誘導する。

## Rationale

- **強制 vs 誘導**: prose（ADR-026「field を変数名から推測するな」）が効かないのは強制機構が無いから。MCP の JSON schema が契約になり、`price` か `price_per_unit` かを迷う余地が構造的に消える。検証は MCP 境界で走り、モデルは検証済みツールとして呼ぶ。
- **受益者=Claude**: 人間向け CLI（案B）を主目的から外したので、「MCP は人間がターミナルから呼べない」という MCP 最大の短所が無効化される。ゆえに手法は MCP に一意。
- **DB ロックの現実**: 当初「MCP を read_only に徹すれば競合ゼロ」と考えたが、access token は 20 分で keepalive の roll 周期（当 LIVE アプリ実測 refresh ≈60分）より短く、**MCP も時々 refresh の書き込みが要る**。したがって純 read_only では成立しない。既存の全 scripts（sync_saxo / import 等）も RW 接続を短命に開閉して on-demand refresh しており、MCP をこの確立パターンに乗せるのが最も整合的。keepalive の役割は「others の access を温める」ことではなく「refresh チェーンを生かしブラウザ再認証を稀にする」backstop である点を、本 ADR で明確化する。
- **context コスト**: ツール schema は session ごとにロードされるが、live 読み取りは少数（〜5–6 ツール）に絞るため軽い（1–2KB/ツール）。ツール数が 40 を超えたら遅延ロード（ToolSearch）へ移行するが、現状は不要。
- **役割分離**: 蓄積層 SQL は duckdb MCP、live 読み取りは新 MCP、判断/執行の分離は ADR-030 と整合。新 MCP は「duckdb に無いもの」だけを担い、既存資産と重複しない。

## Consequences

- **反映先**:
  - 新規 `src/mcp_saxo.py`（仮）＝ live 読み取りツールを公開する stdio MCP サーバ。
  - `.mcp.json` に新サーバを追加登録。
  - `.claude/settings.local.json` の permissions に新 MCP ツールを allow、ad-hoc `python -c ...saxo/duckdb` を deny（案A）。
  - `docs/api/saxo/README.md` の非存在アクセサ記述を削除（ドリフト解消、案A）。
  - `account/transactions.parquet` 等に duckdb VIEW を作成し、既存 duckdb MCP から名前で照会可能に（案A）。
  - CLAUDE.md に「live 情報は新 MCP ツール経由」の導線を追記（accepted 後）。
- **トレードオフ**:
  - Saxo API に field が増えたらツール schema を更新する保守が発生（更新しないと Claude が新 field を知れない）。
  - session ごとに小さな context コスト（ツール schema）。
  - token 失効時は会話層フォールバック（oauth_init）に依存し MCP 単独で完結しない。これは人間のブラウザログインが本質的に要るため意図的（ADR-025）。
  - MCP と keepalive が同時に RW を欲した瞬間は片方が待たされる/リトライ。窓は短命だが皆無ではない。
- **将来の見直しトリガー**:
  - live 読み取りツールが 40 を超えたら ToolSearch（遅延ロード）へ。
  - 人間もターミナルから同じ read を欲したら、案B（`sensei` CLI）を別 ADR で**追加**する（本 ADR を supersede せず共存。CLI と MCP は同じアクセサを共有ラップできる）。
  - RW 競合のリトライが実運用で頻発するなら、token 書き込みを単一オーナーへ直列化する設計を別 ADR で検討。

## Implementation（TDD、Phase 分割）

> 実装は accepted 後。テスト先行（CLAUDE.md / ADR-022）。

- **Phase 0（受益者非依存・先行可）**: (1) `docs/api/saxo/README.md` の非存在アクセサ削除、(2) parquet に duckdb VIEW、(3) permissions で正道へ誘導。案C を待たず着手できる。
  - (3) の実装判断: Claude Code の Bash 権限パターンは**前方一致**で「コマンドが saxo/duckdb を含む」を表現できず、広い `python -c` deny は正当な利用も潰すため**採用しない**。誘導は「新 MCP ツールを allow ＋ CLAUDE.md 導線 ＋ doc-drift 解消」で達成する。
- **Phase 1（サーバ骨組み）**: stdio MCP サーバの雛形。短命 DB 接続（既定 read_only、refresh 時のみ RW 昇格＋バックオフリトライ）。active token 不在/失効時の `AUTH_REQUIRED` 構造化エラー。ここまでをテストで固定。
- **Phase 2（ツール実装）**: `get_account_balances` / `get_positions` / `get_open_orders` / `get_trade_cost` / `get_realtime_quote` を既存アクセサのラップとして実装。各ツールは dataclass → named-field JSON へ整形。`sizing` 用は `spending_power`（`settled_cash_balance` は使わない、ADR-026）。
- **Phase 3（配線・検証）**: `.mcp.json` 登録、permissions allow、CLAUDE.md 導線。`/mcp` で `✓ Connected` を確認し、「残高は？」で Claude が ad-hoc python でなく MCP ツールを使うことを実地確認。

## 検証（2026-07-08）

- **ユニット**: `tests/test_live_reads.py`(18) + `tests/test_mcp_saxo.py`(7) + `tests/test_ledger_views.py`(2)。全 serializer の field 写像・`decide_mode` 3分岐・`_retry_on_lock`・payload の AUTH_REQUIRED 変換・ツール登録/委譲・ビュー生成/存在ガードを固定。フルスイート 902 passed(回帰なし)。
- **end-to-end(実 live)**: `.mcp.json` と同一の `python src/mcp_saxo.py` を stdio MCP クライアントで起動し、5ツール全てを実 Saxo/ yfinance で実行。`get_account_balances`→ 実残高(spending_power 79957)、`get_positions`→ 実建玉13株(3@165.4+10@196)、`get_open_orders`→ 実 OCO 脚(Stop$100/TP$250)、`get_realtime_quote(SOXL)`→ pre 実値・`is_thin` 注記、`get_trade_cost`→ break-even 実算出、未登録銘柄は `UNKNOWN_SYMBOL`。
- **並行性経路の実発火**: 検証中に access が buffer 内で `read_live` が read_write へ昇格し on-demand refresh(`Saxo access token refreshed count=7`)が走ることを確認。稼働中の keepalive とロック競合せず(リトライ吸収)、ADR の並行性設計が実地で成立。
