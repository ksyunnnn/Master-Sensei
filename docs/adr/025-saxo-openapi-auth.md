# ADR-025: Saxo OpenAPI 認証情報の配置設計

Status: proposed
Date: 2026-05-26

## Context

Master Sensei が brokerage の **現金残高・口座別ポジション・通貨情報** を取得できない設計欠陥が顕在化した (2026-05-26 セッション)。

### 顕在化した問題

ユーザが「残現金を SOXL に追加投入するか」を相談した際、以下の質問に DB が答えられなかった:
- 口座 P120136 の現金残高
- 口座 T126816 の現金残高
- NAV (現金 + 含み資産)
- ポジション size が NAV の何 %
- Kelly 推奨 size の算出

`trades` テーブルは個別 trade の `pnl_usd/pnl_pct` を持つが、口座別 cash balance も初期入金額も追跡していない。累計 realized PnL (-$572.60) を出しても残現金には換算不能。

ユーザの Saxo 取引明細 Excel (`Transactions_22013145_2026-03-11_2026-05-25.xlsx`) からは復元可能 (P120136: 21,901 JPY ≈ $138 / T126816: 103,099 JPY ≈ $649) だが、毎セッション手動 DL は摩擦が大きく、自動化が必要。

### 選択肢の絞り込み経緯

Step 1: データ源として **Saxo OpenAPI 直接統合 (D案)** を選択
- Excel sync (C案) と比較し、リアルタイム性・運用摩擦・portability で D 優位
- `saxo_openapi` (pypi, hootnot) wrapper 既存
- 必要 endpoint: `pf.balances.AccountBalancesMe`, `pf.positions.PositionsMe`

Step 2: 認証フローとして **OAuth 2.0 (Authorization Code grant + refresh)** を選択
- 24h Dev Portal token は毎日ブラウザ手動コピペが必要 → SoT 原則 (ADR-008) に反する摩擦
- OAuth なら初回認可後、60〜90日間は無人で refresh 継続可能
- 自動化された scan-market・signal-check 等の skill を将来増やす際の前提条件

Step 3: token 配置として **DB (DuckDB) vs `.env`** が論点に → 本 ADR で確定

### token 配置の論点

OAuth access token は **20 分で失効** し、refresh のたびに refresh token も rotate する (各 refresh で旧 refresh token は無効化)。1セッション中も複数回 rotate するため、`.env` への書き戻しは:
- env ファイル mutation = anti-pattern (12-factor)
- 同時 process が複数あると競合
- 失効履歴・取得経緯の audit が不能
- SIM/Live 環境の token 区別が困難 (単一 `SAXO_TOKEN=` では)

一方 App Key/Secret は **月〜年単位で不変の静的 config** で、性質が異なる。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A. 全部 `.env` (App Key/Secret + token) | 実装最小 | token 自動書き戻しが anti-pattern、audit 不能、multi-env 困難 | 不採用 |
| **B. ハイブリッド (App Key/Secret は `.env`、token は DB)** | **静的config と 動的state の関心分離、ADR-009 精神と一貫、multi-env対応、audit可能** | テーブル 1個追加 | **採用** |
| C. macOS Keychain (`security` cmd 経由) | OS 標準で暗号化保管 | macOS 専用、可搬性低、inspect 手間、過剰 | 不採用 |
| D. 暗号化 vault (HashiCorp Vault 等) | 本格的秘密管理 | 個人 local 用途で過剰 | 不採用 |

## Decision

> **Option B (ハイブリッド) を採用する。** 以下を実施する:
>
> 1. **静的 credentials は `.env`** に配置する:
>    ```
>    SAXO_APP_KEY=...
>    SAXO_APP_SECRET=...
>    SAXO_REDIRECT_URI=http://localhost:8080/callback
>    SAXO_ENVIRONMENT=live   # 'sim' | 'live'
>    ```
>    `.env` は git管理外 (`.gitignore` 確認)、`chmod 600`。
>
> 2. **DuckDB に `auth_tokens` テーブルを新設する。** schema:
>    ```sql
>    CREATE TABLE auth_tokens (
>        id INTEGER PRIMARY KEY,
>        provider VARCHAR NOT NULL,            -- 'saxo' (将来 'fred' 等拡張)
>        environment VARCHAR NOT NULL,         -- 'sim' | 'live'
>        token_type VARCHAR NOT NULL,          -- 'access' | 'refresh'
>        token_value VARCHAR NOT NULL,
>        acquired_at TIMESTAMP WITH TIME ZONE NOT NULL,
>        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
>        acquired_via VARCHAR,                 -- 'oauth_initial' | 'oauth_refresh' | 'dev_portal_manual'
>        refresh_count INTEGER DEFAULT 0,
>        metadata JSON,                        -- response 生 payload (audit)
>        revoked_at TIMESTAMP WITH TIME ZONE,
>        created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
>    );
>    CREATE INDEX idx_auth_active ON auth_tokens(provider, environment, token_type)
>        WHERE revoked_at IS NULL;
>    ```
>    append-only。expired/revoked record は削除せず audit 保持。
>
> 3. **SenseiDB に helper を追加する:**
>    - `save_token(provider, environment, token_type, token_value, expires_at, acquired_via, metadata=None) -> int`
>    - `get_active_token(provider, environment, token_type) -> dict | None` (期限内未失効の最新 1件)
>    - `revoke_token(id, reason)` (refresh失敗時等)
>
> 4. **OAuth クライアント `src/saxo_client.py` を新設する:**
>    - 起動時に `get_active_token('saxo', env, 'access')` を試行
>    - 期限切れなら refresh token で access token 更新 → 両方 `save_token`
>    - refresh token も期限切れなら例外 raise → ユーザに `/saxo-reauth` 実行を促す
>
> 5. **初回認可 CLI `scripts/saxo_oauth_init.py` を作成する:**
>    - ローカル HTTP サーバ起動 (port 8080)
>    - Saxo 認可URLをブラウザで開く
>    - callback で code 受領 → token endpoint 叩いて初回 access+refresh token 取得
>    - DB に保存
>    - 60〜90日に1回再実行
>
> 6. **Saxo Live OpenAPI app の App Key/Secret は 2026-05-26 取得済み** (申請 lead time 想定 1〜2営業日に対し実際は即日発行)。`.env` に `SAXO_APP_KEY_LIVE` / `SAXO_APP_SECRET_LIVE` / `SAXO_AUTH_URL_LIVE` / `SAXO_TOKEN_URL_LIVE` として配置済み。SIM 用変数 (`*_SIM`) は将来用に空欄保持、本実装では参照しない。

## Rationale

### なぜ DB に token を置くか

1. **ADR-009 の精神と一貫**: regime_assessments で入力値スナップショットを必須化したのと同じ思想 — auth state も「いつ取得したか・いつ失効するか・何回 refresh したか」が後から監査可能であるべき
2. **OAuth 仕様への適合**: refresh token は使用ごとに rotate するため、永続化先は「mutation 安全」な store でなければならない。DB は ACID、`.env` は手作業前提
3. **multi-env 自然対応**: SIM/Live を `environment` カラムで分離。`.env` では `SAXO_TOKEN_SIM=` / `SAXO_TOKEN_LIVE=` の二重定義必要
4. **audit & debugging**: refresh 失敗が連続したら DB の `acquired_at`/`expires_at`/`refresh_count` を SQL で時系列確認できる
5. **無人実行と整合**: 将来 cron 化された skill が token を消費しても、`.env` 編集なしで動き続ける

### なぜ App Key/Secret は `.env` か

1. **性質が違う**: アプリ申請時に1回発行、月〜年単位で不変。rotation 概念がない
2. **bootstrap 必要**: DB から credentials を読むには DB 接続が必要、その認証情報を DB に置くと循環
3. **12-factor config**: 配備依存の static 値は env が正解。direnv 等の OS 標準ツールに乗る
4. **token 漏洩時の影響範囲分離**: DB が漏れても App Secret は別ファイルに守られる (depth in defense)

### なぜ Keychain ではないか

- 個人 macOS local 専用なので OS keychain の暗号化は overkill
- `security` cmd 経由の read/write は inspect 困難で debug 摩擦
- 可搬性低 (Linux/Windows 移植不可)
- DB ファイルも `chmod 600` で同等のアクセス制御は可能

## Charter Impact

- **Charter 3.3 MAP 分析**: NAV/cash 数値に基づく Kelly フラクション議論が初めて DB 駆動で可能になる (現在は会話依存)
- **Charter 5.x 自己評価**: 「ポジション size が NAV の何 % で entry したか」が trades に対して計算可能になり、過大ベット/過小ベットの review 精度が向上
- **ADR-001 データガバナンス**: brokerage state を扱う領域を明示的に scope-in する初の ADR (ADR-001 のスコープを補正)

## Consequences

### 反映先

- **新規ファイル**:
  - `src/saxo_client.py` (OAuth wrapper, token lifecycle 管理)
  - `scripts/saxo_oauth_init.py` (初回認可 CLI)
  - `scripts/saxo_oauth_init.py` のテスト
  - `tests/test_db_auth_tokens.py` (DB helper のテスト)
- **既存ファイル変更**:
  - `src/db.py`: `auth_tokens` テーブル定義 + helper 3 メソッド追加
  - `requirements.txt`: `saxo_openapi` 追加
  - `.env.example`: `SAXO_APP_KEY` 等のテンプレート追加 (実値は `.env` に)
  - `.gitignore`: `.env` 確認 (既存のはず)
- **連動する skill 設計 (別 ADR で扱う、本 ADR では対象外)**:
  - `/portfolio-sync` 新設 (balances + positions 取得 → DB の portfolio_snapshots に書き込み)
  - `/entry-analysis` 改修 (NAV ベースの sizing 議論)
  - SessionStart hook で token 期限警告 (例: 残 7日以下で警告)

### token keepalive (2026-06-15 追記、session 50)

Trade #17 の実戦で token 失効が頻発し (1セッション 4回再認証)、約定確認・利確判断の度にブラウザ再認証が初動を中断した。根治として `scripts/saxo_keepalive.py` を追加。

- **判明 (推測でなく公式確認)**: token lifetime に**固定の公式値は存在せず app 依存**。access は公式 20分固定だが、refresh は**公式 doc 例 40分に対し当 LIVE アプリ実測 60分**で食い違う。→ コードは数字をハードコードせず DB の `expires_at` (= Saxo 応答値) を読む設計に統一 (`docs/api/saxo/token-auth.md`、ADR-026 準拠)。
- **設計**: refresh token を**失効直前 (margin) に1回だけ roll** する backstop。access (20分) は温めず in-session `get_access_token()` の on-demand 更新に任せる = **token 再発行を失効周期に1回へ最小化**。access < refresh なので roll 時 access は失効済→`get_access_token()` が rolling refresh を起こす。
- **起動方針**: /sync-saxo 実行時 ＋ ユーザー明示指示のみ。**セッション開始時の自動起動はしない** (oauth ログイン画面で初動が遅れるため)。`run_in_background` のセッション子プロセスでセッション終了時に停止 (launchd/disown による永続化はしない)。lockfile でリフレッサー1本厳守。
- 反映: `scripts/saxo_keepalive.py` (TDD `tests/test_saxo_keepalive.py`)、`docs/api/saxo/token-auth.md`、`/sync-saxo` SKILL に起動ステップ、`.gitignore` に `logs/`。
- 残課題: PC スリープが refresh lifetime を超えると失効は依然不可避 (session 43 教訓)。これは再認証必須で keepalive では回避できない。

#### DB ロックを sleep 中に保持しない (2026-06-15 追記、session 50)

初版 keepalive は `main()` で read-write 接続を1本開き、`run_keepalive` がそれを**ループ全寿命 (最大300秒の sleep 中も含む) 保持**していた。DuckDB の read-write 接続はファイル**排他**ロックを取るため、keepalive 稼働中はずっと他プロセスを弾く。実害:

- セッション終了時の **Stop hook (`session_stop_check.py`、read_only) が毎回失敗** (`IOException: Conflicting lock is held in PID <keepalive>`)。未解決予測の期限チェックがスキップされる。
- `/sync-saxo` の import や `close_trade()` 等、同セッションの DB 書き込みも同時実行不可。

**修正**: 接続を **tick ごとに開閉**し、**sleep 前に閉じる**。さらに poll (失効残りの確認=読み) は **`read_only` (共有ロック)** で Stop hook 等の読み取りと共存させ、**refresh (token 書き込み) の瞬間だけ read-write (排他ロック)** を短時間取る。これで排他ロックは「実際にトークンを roll する稀な瞬間」だけに縮小される。

- `run_keepalive(client, db, ...)` → `run_keepalive(session_factory, ...)` に変更。`session_factory(read_only=...)` は `(client, db)` を yield する context manager (`make_session_factory(db_path, config)` が生成)。
- read_only 接続では DuckDB が CREATE を拒否するため `SenseiDB(conn, init_schema=False)` を追加 (スキーマ既存が分かっている読み取り専用接続用、後方互換: 既定 True)。
- 検証: keepalive 稼働中に read_only 接続・`session_stop_check.py` がエラーなく成功することを実機確認。回帰テスト `test_run_keepalive_holds_no_session_during_sleep` 他で sleep 中の非保持・poll=read_only/refresh=read-write を固定。

### トレードオフ

- ストレージ: token rotation で `auth_tokens` が成長。1日 ~20 record × 365日 = 7,300 record/年、1record < 1KB なので影響軽微
- 実装コスト: 初期 5-8 時間 (saxo_openapi 動作確認、OAuth CLI、テスト)
- Saxo API 仕様変更リスク: wrapper 経由でも raw `requests` でも同じリスク。endpoint URI 変更時は src/saxo_client.py のみ修正
- Live OpenAPI app 申請 lead time 1〜2営業日 (SIM 環境で並行開発可能)

### 見直しトリガー

- **複数 broker 対応が必要になった場合** → `auth_tokens` の `provider` カラム拡張で対応済み (再設計不要)
- **token rotation 頻度が secondary 単位に上がった場合** (Saxo 仕様変更等) → DB I/O コスト見直し
- **マルチユーザ化した場合** (現状は個人専用) → `user_id` カラム追加、credentials 暗号化検討
- **Master Sensei が VPS/cloud 移行した場合** → Vault 等の本格 secret 管理への移行検討

### 実装段階

| Phase | 内容 | 状態 / 前提 |
|-------|------|------|
| 1 | Saxo SIM app 作成 + Live app 申請 | **完了** (2026-05-26、Live は審査待ちなしで即発行) |
| 2 | `auth_tokens` テーブル + `SenseiDB` helper 実装 + テスト | Phase 1 完了済み、即着手可 |
| 3 | (optional) SIM 環境で OAuth flow 動作確認 | **省略可**。SIM の役割は (a) Live app 申請の前提条件、(b) 発注テスト用、(c) API 探索用。本プロジェクトは Live app 発行済み + read-only のためいずれも不要。rate limit 観点でも 1セッション 2 req/分 vs 120 req/分 で余裕あり、SIM 節約効果ゼロ |
| 4 | Live 環境で OAuth flow 実装 + 動作確認 (主路) | Phase 2 完了後 |
| 5 | `/portfolio-sync` skill 新設 (別 ADR) | Phase 4 完了後 |

`.env` の `SAXO_*_SIM` 用 4変数は将来 24h dev token で素早く動作確認したい場合に備え空欄保持。コードからは参照しない。

### SIM スキップの根拠 (調査結果)

公式ドキュメント (https://www.developer.saxo/openapi/learn/rate-limiting) で確認した rate limit:
- アプリ全体: 1,000万 req/日
- セッション × サービスグループ: 120 req/分

Master Sensei の用途 (balances + positions = 2 req/セッション) では制限の **60倍以上の余裕**。「SIM で quota 節約」の動機なし。OAuth token に「消費」概念は OAuth 仕様上そもそも存在せず、rate limit のみが制約。

SIM/Live で rate limit が別カウントかは公式ドキュメントに記載なし (credentials が独立なので別カウントの可能性高いが推測)。本プロジェクトの request 量規模ではこの差異も実害ゼロ。

### 実装タイミング

- 設計確定: 本 ADR で 2026-05-26
- 実装: Phase 2-4 は本日〜翌日。Phase 5 は別 ADR で起案

## 関連 ADR

- **ADR-026 (外部 API field 解釈規律)**: 本 ADR 実装中に Saxo Balance field 解釈で致命的誤りが発生。その教訓を一般化した規律。Saxo は ADR-026 適用第1号 (`docs/api/saxo/` 完全文書化、意味的アクセサ実装)。今後の Saxo endpoint 追加・他 provider 統合時は ADR-026 を必読。
