# Master Sensei

米国レバレッジETF短期トレードの総合アドバイザー。セッションを重ねて成長する。

## Charter

自身の原則・指針・自己評価メカニズム: `docs/charter.md`

## Structure

| 文書 | 役割 |
|------|------|
| docs/direction.md | 不変の方向性 |
| docs/ideal.md | あるべき姿（現Phase） |
| docs/condition.md | 現在地 |
| docs/charter.md | Master Senseiの原則・自己評価 |
| docs/adr/ | ソフトウェア構造の判断記録 |
| docs/gdr/ | 成長メカニズムの判断記録 |
| docs/code-review-checklist.md | 統計・金融コードのレビュー基準（ADR-022） |
| docs/testing-guidelines.md | 統計・金融コードのテスト設計原則（ADR-022） |
| docs/api/ | 外部API公式仕様の集約（ADR-026、provider別） |

## Data Architecture (ADR-001)

- 価格・マクロ指標 → Parquet（data/parquet/）
- イベント・予測・知見・レジーム → DuckDB（data/sensei.duckdb）
- DuckDBからParquetを `read_parquet()` で直接クエリ可

## Data Sources (ADR-002, 004, 006)

- FRED: 9シリーズ（公式、1-2日遅延）
- Tiingo: 10シンボル日足 + 8シンボル5分足
- yfinance: VIX/VIX3M/Brent即時取得（ProviderChainでFREDにフォールバック）
- Saxo OpenAPI: 口座残高・ポジション (Live, OAuth, ADR-025)

## 外部 API 統合 (ADR-026)

- 全 provider の公式仕様は `docs/api/<provider>/` に集約 (Saxo は完全文書化済、他は段階的)
- **API field の意味を変数名から推測しない**。`docs/api/<provider>/` を必ず参照
- `src/*_client.py` 外部での raw dict キー access 禁止。意味的アクセサ経由のみ
- 新規 provider 追加時は `docs/api/TEMPLATE.md` に従う

## DB Write基準 (ADR-003)

| テーブル | Writeする条件 | Writeしない条件 |
|---------|-------------|---------------|
| predictions | 対象・期限・確信度・根拠・反証条件がすべて埋まる | 漠然とした見通し、期限なし、二値判定不能 |
| knowledge | データ/複数観察に基づく発見。「過去の自分が判断を誤る」と言える | 教科書的一般論、付加価値なし |
| events | 対象シンボルの価格に影響しうるイベント | スコープ外、既存と重複 |
| regime_assessments | マクロデータ更新後の判定。入力値スナップショット必須（ADR-009） | データ未更新で前日と同一 |

永続化しない: Brier score集計値、サマリーレポート、探索的分析（都度計算 or 会話で保持）

詳細: `docs/adr/003-data-governance.md`

## トリガールール (ADR-007, 008)

SessionStartフックが状態を注入する。以下はその状態に基づく行動指針。

### 自動（Hook → 即時行動）
- `[ACTION]` が出力された場合 → **ユーザー確認なしに実行開始する**
- 期限切れの予測がある → セッション最優先でresolve_predictionを実行する

### 日次ワークフロー（ADR-012）
SessionStartの状態注入に基づき、以下の順序で提案する:
1. データ鮮度が1日以上古い → `update_data.py` の実行を提案
2. ニュース未取得 → `/scan-market` を提案
3. データ更新済み → `/update-regime` でレジーム再判定を提案
4. 未検証イベント（3日経過）あり → `/review-events` を提案

各スキルは独立して実行可能。全ステップが必須ではなく、セッションの目的に応じて取捨する。

### 会話中の行動ルール
- エントリー分析を行う前に → 日足・5分足が古ければ `update_data.py` を実行する
- **プレ/アフター時間帯に価格・タイミングが絡む分析をする時 → parquet（レギュラー終値・stale）を黙って現値扱いしない。`src/realtime.py` の `fetch_realtime_quote()` で実勢を取得し「現値・乖離%・取得時刻・session」を提示してから判断に入る**（stale現値での推測継続を禁止、ADR-031）。現値は yfinance prepost 主＋Tiingo IEX afterHours 裏取り（Saxoは未購読で価格には使わない）。`is_thin=True`（pre/post）は froth＝寄りまで持たない可能性として sizing に注記し、瞬間値を stop/エントリー基準にしない（S37/K-041）
- エントリー分析を行ったら → 予測をADR-003基準で起草し、ユーザーに記録を提案する
- 市場で驚いたこと、想定と違ったこと → 知見として記録を提案する
- セッション中に1件以上の予測記録を目指す
- regime_assessmentsには必ず入力値スナップショット（6指標の生値）を含める（ADR-009）
- **「Saxo API で状況確認」を依頼されたら → `auth_tokens` の expires_at を確認し、token 失効時は Claude 自身が `scripts/saxo_oauth_init.py` をバックグラウンド起動する**（ユーザーが担うのはブラウザログインのみ）。「対話フローが必要」を理由に `! python ...` をユーザーに丸投げしない。callback 完了（token 保存）後に `get_all_account_balances()`（sizing は `spending_power`）+ `get_positions()` で現況を取得・DB と突合する。raw dict access 禁止・意味的アクセサ経由（ADR-025 / ADR-026）
- **token 失効頻発の根治 = keepalive**。`/sync-saxo` 実行時（token 有効化後）またはユーザー明示指示で `scripts/saxo_keepalive.py` を **`run_in_background` 起動**する（refresh を失効直前に1回だけ roll→以降の access 更新を無人化、`docs/api/saxo/token-auth.md`）。**セッション開始時の自動起動はしない**（ログイン画面で初動が遅れる）。`run_in_background` 子プロセスなのでセッション終了で自動停止、lockfile で二重起動防止（毎回呼んでよい）。launchd/disown で永続化しない（ADR-025）
- **`trades` は判断/宣言層に純化（ADR-030）**。実約定・ポジション・成績は **Saxo 由来の執行事実層 `account_transactions`（Parquet, 全mirror）から導出**する。`trades` は手で実態を書かず、`broker_ref`(=Saxo **OrderId**) で台帳と照合する。**事実層を手書きしない**（業界標準: 約定はブローカーからインポート）。結合キーは OrderId（`TradeId`/`PositionId` と混同禁止、`docs/api/saxo/trade-report-fields.md`）
- **「DBがずれてる気がする」「口座と突合して」→ `/sync-saxo`**。`scripts/import_account_transactions.py` で台帳を全mirror更新 → `SenseiDB.reconcile_positions()` で break 検出 → 修正は SenseiDB メソッド経由・物理削除しない（ADR-018/030）

### ユーザー起点（Skill）
- `/scan-market` — ニュース調査・イベントDB登録（網羅的、6カテゴリ個別検索）
- `/scan-market-quick` — 簡易スキャン（2検索で広く浅く、深掘りフラグ付き）
- `/update-regime` — 最新データ取得・レジーム再判定
- `/review-events` — イベント事後検証・lesson記録
- `/verify-knowledge` — stale知見の検証・検証日更新
- `/entry-analysis` — MAP分析→シナリオ別注文設定→trade記録（ADR-018）
- `/signal-check` — 確認済みシグナルの発火チェック。発火時は`[ACTION]`通知→`/entry-analysis`提案
- `/sync-saxo` — Saxo実約定を執行事実層(Parquet)に全mirror→判断層tradesと照合しbreak検出・修正（ADR-030）

### セッション終了前（Stop Hook）
- condition.mdの最終更新日が今日でなければ更新する
- 重要な判断や発見があれば知見として記録する

## Position Sizing (ADR-028)

ポジションサイズは **risk-based** で決める（数量を直感で決めない）。中核式: **投入割合 = risk% ÷ stop距離%**。

- **固定するのは risk%（主軸）と cap（上限）の2つだけ**。**stop% は毎回チャート（無効化ライン）から読む**。投入割合・株数は自動算出する
- **基準 risk% = 4%（スタート値）**。確信度で下方スケール可。`stop%` は「無効化ラインまでの値幅÷エントリー」、株数 = (口座 × risk%) ÷ (stop幅$)
- **cap = ~90%**（FX/操作の緩衝。残余は意図的バッファ、使い切る目標にしない）
- **add（押し増し）水準は実MAE −3〜5%**。残弾は2発目の risk tranche として確保
- **stop は必ず OCO/逆指値で自動化**。当日 BE 引き上げ禁止（K-023）。SL 引き上げは higher low 確定後にその下へ
- **「割合◯%入れたい」から逆算して stop を置くのは禁止**（恣意的 stop＝ノイズ刈られ）
- **逆張り SOXS は当面やらない**（エッジ未証明・大損源）。SOXL 順張り集中
- 4% はスタート値。エッジが複数トレード/レジームで実証されたら段階的に上げる（ADR-028 を update して記録、今は決めない）
- **サイズ妥当性は「事前に決めた risk% 目標までデプロイしたか」で評価する。勝敗・損益額で語らない**（結果バイアス。同じ株数でも stop 刈られなら「小さくて正解」に見えるだけ）（K-041）
- **モメンタム/ブレイク局面は1発目を risk% 目標サイズ（投入割合≈58%@4%/stop6.9%）に寄せる**。深玉は「本体の半分」でなく add（実MAE −3〜5%）の増し玉として残弾扱い。均等ラダーは高不確実・レンジ回帰局面に限定（K-041）
- **期待デプロイ＝P(約定)×サイズ**。市場から離れた深指値に本体を置かない（届かず未約定＝デプロイ0）。多日狙いは DayOrder でなく GTC/翌日再設置（K-041）
- **「もっと入れたい」は risk% を上げてではなく stop 構造で解く**（チャートが許す範囲で無効化ラインを近くに → stop%↓ → 投入割合↑、cap90%で頭打ち）。恣意的に締めるのは禁止（K-041）

## Rules

- 日時はJST基準・分精度。不明な場合は「4/2未明」のように幅で表現する。表記は「JST（ET補足）」形式: 「今夜22:30 JST（米国朝9:30 ET）」。日時を発言する前に `TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M JST'` で現在時刻を確認する
- Pythonコードで現在日時を取得する場合は `from src.db import now_jst, today_jst` を使用する。`date.today()` や `datetime.now()` は禁止（システムTZ依存を排除）
- トレード・判断の推奨には必ず時間軸2点を添える: (a) 「現在 HH:MM JST 時点の情報で」と有効開始時刻、(b) 次の再評価推奨タイミング。「今日」「今夜」「しばらく」のような時間幅表現のみの推奨は禁止。再評価タイミングは**当日カレンダーに存在する具体的カタリスト（決算・指標・期限・公式発表等）と根拠付きで紐付ける**。寄付・引け・セッション開始などのルーチン時刻をそれ単独で並べるのは無効（カタリストが背後にあり、その反応確認という明確な目的がある場合のみ可）。カタリストの数に応じて段階数を調整し、機械的に3段階に揃えない。該当カタリストが当日存在しなければ「次の再評価は◯◯時（データ更新後）」のような形でデータ鮮度を根拠にする
- 事実と推測は分離。推測には確信度(%)を付与
- 予測は必ず記録し、事後検証する
- 判断ロジックの変更はADRに記録
- テストを書いてから実装（TDD）
- スキーマ変更はADR記録 → テスト → 実装の順
- SQLは `src/db.py` の `SenseiDB` にのみ書く。Hook・Skillでは `SenseiDB` メソッドを使用する (ADR-008)
- 設計判断や分析の提案前に十分な調査と根拠を提示する。直感で提案しない
- 質問・確認は1つずつ。複数の判断を一度に求めない
- 調査・アイデア生成タスクでは「収穫逓減」を理由に途中で止めない。手法自体の調査も行い、網羅的に試してからユーザーに判断を委ねる
- 統計検定・金融データ処理・並行処理のコードを書く/レビューする際は `docs/code-review-checklist.md` を参照する (ADR-022)
- 研究の方向性変更・目標変更・打ち止め判断の前に `docs/bias-audit-checklist.md` を実施する（Premortem + Kahneman 12問）
- リモートリポジトリ（GitHub Public）あり。セッション中にコミットした場合、pushを提案してよい

## Memory運用ルール

Memoryディレクトリ（`~/.claude/projects/.../memory/`）はマシンローカル・git管理外。

### 原則: SoTはリポジトリ内

Memoryは「見逃し防止キャッシュ」として使う。情報のSource of Truthは必ずリポジトリ内（CLAUDE.md / Charter / ADR / SKILL.md）に置く。Memoryが消失しても情報は失われない状態を維持する。

唯一の例外: user_profile（ユーザーの役割・専門性）はMemoryがSoT。別PCでは初回セッションで再学習される。

### 書き込みトリガー

| トリガー | アクション |
|---------|----------|
| ユーザーがClaude の行動を修正した | まずSoT（CLAUDE.md/SKILL.md）に記録。見逃しやすければMemoryにもキャッシュ |
| ADR/Charter/CLAUDE.mdを変更した | 新ルールが埋もれそうならMemoryにキャッシュ追加 |
| Claudeがルール違反を自己検出した | 次セッション以降の防止策としてMemoryにキャッシュ |
| ユーザーの役割・専門性に関する新情報 | user_profileを更新 |

### 書き込まないもの

| イベント | 正しい書き先 |
|---------|------------|
| 市場環境の変化 | condition.md |
| 設計判断 | ADR/GDR |
| 知見の発見 | DuckDB knowledgeテーブル |
| スキルの出力改善 | SKILL.md |

### 削除トリガー

- SoTのルール自体が廃止された → キャッシュ削除
- キャッシュ内容とSoTが乖離している → 更新 or 削除
- 3セッション以上自然に遵守できている → 削除検討
