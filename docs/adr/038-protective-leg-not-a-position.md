# ADR-038: 保護脚を建玉として数えない（trades.parent_trade_id）

Status: accepted
Date: 2026-08-20

## Context

IFD-OCO で建玉に付ける保護脚（決済指値 TP / 決済逆指値 SL）は、判断層 `trades` に
`status='placed'` の行として起票している。発注＝意思決定の事実なので記録自体は正しい
（ADR-027 / ADR-030）。

問題は **`trades` が全行を建玉として扱う**ことにある。`reconcile_positions()` は

```sql
SELECT instrument, SUM(quantity) FROM trades WHERE status='filled' AND exit_date IS NULL
```

を保有申告としており、保護脚が約定した事実を `status='filled'` で記録すると、
**存在しない建玉を申告してしまう**。

🔬 2026-08-19 の SOXL 24株決済で実際に詰んだ。SL $120.00 の脚
（`trades.id=40` OrderId 5434515782 / `id=42` OrderId 5434516704）が約定して
建玉を閉じたが、

- `filled` にすると `exit_date IS NULL` のため **+24株の建玉申告**になり二重計上
- `cancelled` / `expired` は事実に反する（実際に約定している）
- 放置すると `reconcile_open_orders()` が `placed` のまま毎回 break を報告し続ける

どの遷移も選べず、照合が `[注文]` 層の break を抱えたまま前に進まない状態になった。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A. 脚を `trades` に起票しない | 建玉との混同が原理的に起きない | 保護をどこに置いたかの意思決定記録が消える。ADR-030 の「trades＝判断/宣言層」に反する | 不採用 |
| B. 脚に `exit_date` を入れて建玉から外す | 列の追加が要らない | `close_trade()` が pnl を計算するため、SL $120.00 → 約定 $120.03 の **+$0.36 という無意味な損益**が成績集計に混入する | 不採用 |
| C. 脚であることを列で表し、建玉集計から除外する | 意思決定記録を保ちつつ二重計上を断つ。将来の OCO でも自動的に効く | スキーマ変更（ADR → テスト → 実装） | **採用** |

## Decision

> `trades` に **`parent_trade_id INTEGER`** を追加する。値が入っている行は
> 「その trade に付随する保護脚（決済注文）」であって**独立した建玉ではない**。
>
> `reconcile_positions()` の保有申告から `parent_trade_id IS NOT NULL` の行を除外する。
> 成績集計でも同様に除外する（損益は親 trade が持つ）。
>
> 保護脚の `status` は通常のライフサイクル（`placed` → `filled` / `cancelled` /
> `expired`）をそのまま使う。約定した脚は `filled` と記録してよく、
> 建玉として数えられることはもう無い。

既存の 4 行を遡って紐付ける:

| id | 内容 | parent_trade_id |
|---|---|---|
| 39 | OCO TP $160.50（id=37 の決済脚） | 37 |
| 40 | OCO SL $120.00（id=37 の決済脚、2026-08-19 約定） | 37 |
| 41 | OCO TP $160.50（id=38 の決済脚） | 38 |
| 42 | OCO SL $120.00（id=38 の決済脚、2026-08-19 約定） | 38 |

## Rationale

**なぜ脚を消さないか**: 「どこに保護を置いたか」は判断の記録であり、
後から消すと自分の意思決定を検証できなくなる（ADR-018 の物理削除禁止と同じ理由）。
ADR-030 は `trades` を判断/宣言層と定めており、発注はまさに宣言である。

**なぜ `exit_date` で逃げないか**: `close_trade()` は必ず
`(exit_price − entry_price) × quantity` を計算する。脚の `entry_price` は
**発注価格**（SL のトリガー値 $120.00）であって建値ではないため、
算出される +$0.36 は経済的な意味を持たない。成績集計を汚す。

**親子の割当根拠**: 2026-08-19 の 4 脚は OrderId の連番隣接で親に割り当てている
（`5434516702`=id38 の直後が `703`/`704`）。両ブラケットは価格・数量が同一
（SL $120.00 / TP $160.50 / 12株）なので、どちらに割り当てても risk 構造と損益は変わらない。
台帳の sell fill（OrderId `5434515782` / `5434516704`、いずれも $120.03）も
この割当と矛盾しない。

## Consequences

- **反映先**: `src/db.py`（`trades.parent_trade_id` 列、`add_trade()` の引数、
  `set_trade_parent()`、`reconcile_positions()`）、`.claude/skills/entry-analysis/SKILL.md`
- **今後の OCO 起票では保護脚に必ず `parent_trade_id` を付ける**。付け忘れると
  約定時に建玉として二重計上され、本 ADR 以前と同じ詰みが再発する。
- **トレードオフ**: `trades` が「建玉」と「注文」の2種類の行を持つことが明示的になる。
  将来 orders テーブルへ分離する余地は残るが、現時点では列1本で足りる。
- **見直しトリガー**: 保護脚以外にも「建玉でない trades 行」が現れたら
  （例: 分割約定の子注文）、`parent_trade_id` の意味が過負荷になるので
  行種別を表す列への一般化を検討する。
