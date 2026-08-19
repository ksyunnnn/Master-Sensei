---
name: sync-saxo
description: Saxoの実約定を執行事実層(Parquet)に全mirror取得し、判断層tradesと照合してbreak(乖離)を検出・修正提案する。DBがずれていないか定期確認に使う。
---

Saxo 照合ワークフローを実行してください (ADR-030)。判断層 `trades`(宣言) と
執行事実層 `account_transactions`(Saxo 由来の実約定) を突合し、乖離(break)を直す。

差分がなければ数秒・1ステップで終わる。重い全 mirror は走らせず、
`scripts/sync_saxo.py` が「無言 token → テール窓 mirror → **3層照合**」を機械的に実行する。
3層 = ①ライブ建玉↔台帳 ②台帳↔trades ③ライブ注文↔trades placed（ADR-030 Phase 7）。
加えて **closedpositions 説明層**が booking 遅延(T+1)を切り分ける（ADR-036）。
**口座状況も注文も全部スクリプトが照合する**（人間が手でライブを引いて突き合わせる作業は無い）。

## タイムゾーン

現在時刻(JST): !`TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M JST'`

## 手順

### 1. 一発実行

```bash
python scripts/sync_saxo.py
```

スクリプトが内部で行うこと:
- **無言 token 確保**: `get_access_token()` を呼ぶだけ。refresh token が生きていれば
  自動更新で無言通過する。**手動で `auth_tokens.expires_at` を読む点検は不要**。
- **テール窓 mirror**: 既存 parquet の最新 trade_date から overlap 7日だけ遡って
  reports/trades + bookings を再取得し、`broker_ref` で upsert マージ(全年は回さない)。
  窓より前の遡及訂正を拾い直したい時だけ `--full` を付ける。
- **ライブ snapshot 取得**: `get_live_positions()` + `get_open_orders()`(各1コール、安い)。
- **3層照合**:
  1. **ライブ建玉 ↔ 台帳 net** — mirror 漏れ検出。乖離時は窓を `tail→30d→90d→全年` と
     段階拡大して**自動で再mirror→再照合**し、解消した時点で止める(重い全年は最後の手段)。
  2. **台帳 net ↔ trades 申告** — クローズ済未反映/未記録エントリーの検出(従来)。
  3. **ライブ注文 ↔ trades placed** — placed の改定/不発/未記録の検出(台帳に出ない層)。
  全層一致なら `✓ 差分なし (ライブ建玉↔台帳↔trades 一致 / 注文も一致)` で終了。
- **closedpositions 説明層 (ADR-036)**: 決済当日は reports/trades が booking 未着で
  台帳に sell 行が入らない。`/port/v1/closedpositions/me` を1コール取得し、
  ①「ライブ建玉=0 / 台帳net>0」が決済で過不足なく説明できれば `ℹ [booking待ち]` として
  break から外す（**窓拡大の前**に判定する。決済当日の窓拡大は必ず空振りするため）。
  ②台帳に対応する決済脚が無いものを `ℹ [未計上]` と名指しする（同日往復の死角、issue#20）。
  未計上がある時は `✓ break なし (ただし未計上の決済 N件)` と表示し「差分なし」と断言しない。

終了コード: `0`=break なし（未計上の決済が残っていても 0） / `1`=break あり /
`2`=token 失効(`AUTH_REQUIRED`)。

### 2. `AUTH_REQUIRED`(exit 2)が出たら — Claude が認証を起動する

refresh token も失効している(セッション間が空いた)場合のみ発生する。**Claude 自身が**
`scripts/saxo_oauth_init.py` を `run_in_background` 起動する(ユーザーが担うのはブラウザ
ログインのみ。`! python ...` をユーザーに丸投げしない。CLAUDE.md / ADR-025)。
ログイン完了(token 保存)後、**keepalive を起動**してから sync を再実行する:
```bash
python scripts/saxo_keepalive.py   # run_in_background=true で起動 (失効頻発の根治)
```
keepalive は refresh token を失効直前に1回だけ roll し以降の access 更新を無人化する
(`docs/api/saxo/token-auth.md`)。`run_in_background` のセッション子プロセスで終了時に自動停止
(永続化しない)。lockfile で二重起動を防ぐので毎回呼んでよい。**セッション開始時の自動起動は
しない**(ログイン画面で初動が遅れるため)。

### 3. break(exit 1)が出たら — 人間が1件ずつ確認して修正

スクリプトが各 break を層タグ付き(`[live↔台帳]`/`[台帳↔trades]`/`[注文]`)で分類して
出力する。曖昧でない遷移のみ修正、曖昧は1件ずつ確認する:

| 層 | break | 意味 | 修正 |
|----|-------|------|------|
| 台帳↔trades | trades=建玉中 だが ledger net=0 | クローズ済未反映 | `close_trade()`(exit を台帳の sell fill から) |
| 台帳↔trades | ledger net>0 だが trades 申告なし | 未記録エントリー | `add_trade(status='filled', broker_ref=OrderId)` |
| 台帳↔trades | 数量不一致(両方非ゼロ) | 注文改定/部分約定の未反映 | `set_trade_broker_ref()` / 値更新 or 旧 expired+新規起票 |
| 注文 | live_only(ライブに注文・trades未記録) | placed 未起票 | `add_trade(status='placed', broker_ref=OrderId)` |
| 注文 | trades_only(placed だがライブに無し) | 約定/失効/取消 | filled は再mirror で約定反映 / `update_trade_status('expired'/'cancelled')` |
| 注文 | placed_no_ref(broker_ref 未設定) | OrderId 欠落 | `set_trade_broker_ref()` で補完 |
| live↔台帳 | ライブ建玉≠台帳(再mirror後も残存) | **真の乖離** | 全年mirror でも埋まらない＝reports/trades 欠落 or instrument 解決失敗を要調査 |

**live↔台帳 の乖離はスクリプトが自動で窓拡大→再mirror して埋めようとする**。それでも残った
ものだけが上表の「真の乖離」として出る(手で台帳を書かない。事実層は Saxo が SoT)。

**修正は SenseiDB メソッド経由のみ**。物理削除はしない(ADR-018 後知恵バイアス排除)。
修正対象は判断層 `trades` のみ(事実層 `account_transactions` は手書きしない)。
修正後にもう一度 `python scripts/sync_saxo.py` を実行し、`✓` 行を確認する。

**`ℹ [booking待ち]` / `ℹ [未計上]` は break ではない**（人間の修正対象でもない）。
reports/trades への計上を待ち、台帳に sell 行が入ってから `close_trade()` する。
台帳より先に `trades` を閉じると 台帳↔trades が新たに破れる（3層照合は台帳を真とするため）。

## 注意

- 入出金・現金移動(deposit/withdrawal)も mirror 対象 (ADR-030 Phase 5)。
  `reports/bookings` の `AssetType='Cash'` 行から取り込む (`docs/api/saxo/booking-fields.md`)。
  現金行は建玉照合に干渉しない (`reconcile_positions` は buy/sell のみ集計)。
- 結合キーは **OrderId** (`trades.broker_ref` ↔ `ledger.order_id`)。`TradeId`/`PositionId`
  と混同しない (docs/api/saxo/trade-report-fields.md)。
- ライブ状態(現保有/注文)は保存しない。履歴は `account_transactions`(Parquet) が SoT。
