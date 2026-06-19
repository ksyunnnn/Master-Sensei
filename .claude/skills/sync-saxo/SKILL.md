---
name: sync-saxo
description: Saxoの実約定を執行事実層(Parquet)に全mirror取得し、判断層tradesと照合してbreak(乖離)を検出・修正提案する。DBがずれていないか定期確認に使う。
---

Saxo 照合ワークフローを実行してください (ADR-030)。判断層 `trades`(宣言) と
執行事実層 `account_transactions`(Saxo 由来の実約定) を突合し、乖離(break)を直す。

差分がなければ数秒・1ステップで終わる。重い全 mirror は走らせず、
`scripts/sync_saxo.py` が「無言 token → テール窓 mirror → reconcile」を機械的に実行する。

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
- **reconcile**: trades vs 台帳の純ポジションを突合。一致なら `✓ 差分なし` で終了。

終了コード: `0`=差分なし / `1`=break あり / `2`=token 失効(`AUTH_REQUIRED`)。

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

スクリプトが各 break を ADR-030 のカテゴリに分類して出力する。曖昧でない遷移のみ修正、
曖昧は1件ずつ確認する:

| break | 意味 | 修正 |
|-------|------|------|
| trades=建玉中 だが ledger net=0 | クローズ済未反映 | `close_trade()`(exit を台帳の sell fill から) |
| ledger net>0 だが trades 申告なし | 未記録エントリー | `add_trade(status='filled', broker_ref=OrderId)` |
| 数量不一致(両方非ゼロ) | 注文改定/部分約定の未反映 | `set_trade_broker_ref()` / 値更新 or 旧 expired+新規起票 |
| placed だが対応注文も fill も無い | 不発/失効 | `update_trade_status('expired'/'cancelled')` |

**修正は SenseiDB メソッド経由のみ**。物理削除はしない(ADR-018 後知恵バイアス排除)。
修正後にもう一度 `python scripts/sync_saxo.py` を実行し、`✓ 差分なし` を確認する。

### 4. ライブ未約定注文の照合(必要時のみ・別ステップ)

スクリプトは台帳(fill)ベースで照合する。**placed 注文の改定/不発**は fill が無いため
台帳照合では出ない。注文まわりが疑わしい時だけ手動で突合する(意味的アクセサ未整備=
raw dict access につき本体に入れない。ADR-026):
```python
from src.saxo_client import SaxoClient
client = SaxoClient(db)
orders = client._api_get("/port/v1/orders/me").get("Data", [])  # 未約定注文
```
DB の `get_pending_orders()` と突合し、`OrderId` が `trades.broker_ref`(placed行) と
一致するか確認する。

## 注意

- 入出金・現金移動(deposit/withdrawal)も mirror 対象 (ADR-030 Phase 5)。
  `reports/bookings` の `AssetType='Cash'` 行から取り込む (`docs/api/saxo/booking-fields.md`)。
  現金行は建玉照合に干渉しない (`reconcile_positions` は buy/sell のみ集計)。
- 結合キーは **OrderId** (`trades.broker_ref` ↔ `ledger.order_id`)。`TradeId`/`PositionId`
  と混同しない (docs/api/saxo/trade-report-fields.md)。
- ライブ状態(現保有/注文)は保存しない。履歴は `account_transactions`(Parquet) が SoT。
