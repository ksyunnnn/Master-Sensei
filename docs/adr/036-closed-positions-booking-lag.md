# ADR-036: 決済当日の照合に closedpositions 層を使う（booking 遅延の切り分け）

Status: accepted
Date: 2026-08-20
Extends: ADR-030（判断層と執行事実層の分離）

ADR-030 の結論（執行事実層の SoT は Saxo 由来の `account_transactions`、判断層
`trades` は手で実態を書かない）は**変更しない**。本 ADR はその前提を保ったまま、
決済当日に事実層が空白になる死角を塞ぐ。

## Context

執行事実層 `account_transactions`（Parquet）の供給源は `/cs/v1/reports/trades/` で、
**booking は T+1** である。したがって決済当日は台帳に sell 行が入らない。

この状態で `/sync-saxo` の3層照合を回すと、`reconcile_live_positions` が
「ライブ建玉=0 / 台帳net>0」を検出し、**mirror 漏れ＝真の乖離**と誤って分類する。
現実装はそれを受けて mirror 窓を `tail→30d→90d→全年` と段階拡大するが、
**reports/trades に sell 行が存在しない以上どの窓でも埋まらず、4段階すべてが空振り**する。

🔬 2026-08-19 に実際に発生した。SOXL 24株を逆指値で決済（約定 8/19 23:07:32 JST /
$120.03）した翌朝の `/sync-saxo` が、全年 mirror まで escalate した末に
break 3件を報告して停止した。内訳は `[live↔台帳]` 1件と `[注文]` 2件で、
**3件とも同一原因（booking 未着）**だったが、照合器はそれを区別できなかった。

さらに悪いことに、この状態では判断層 `trades` を前に進められない。台帳が遅れている間に
`close_trade()` を先行させると `trades_open_qty=0` と `ledger_net_qty=24` が
**新たに破れる**（3層照合は「台帳が真」を前提に組まれているため）。結果として
**決済当日は照合が構造的に停止する**。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A. booking 到着（T+1）を待つ | 実装ゼロ。事実層の単一ソース原則を保つ | 決済のたびに照合が1日停止する。当日中の帰属分析ができず、空白を推測で埋める誘因が生まれる（実際 2026-08-19 に誤帰属を生んだ） | 不採用 |
| B. `closedpositions` を台帳に書き込む | 当日から台帳が完全になる | 事実層に2つの供給源が混在し、booking 到着時に二重計上の解決が要る。`closedpositions` は `OrderId` を返さず upsert キー（`broker_ref`）を作れない | 不採用 |
| C. `closedpositions` を**照合専用の説明層**として使う（台帳には書かない） | 台帳の SoT は `reports/trades` のまま。break を benign/真の乖離に切り分けられる。窓拡大の空振りを事前に止められる | 層が1つ増える。instrument 単位でしか照合できない | **採用** |

## Decision

> `/port/v1/closedpositions/me` を **照合専用の説明層**として導入する。
> 執行事実層 `account_transactions` には**書き込まない**（SoT は `reports/trades` のまま）。
>
> `reconcile_live_positions` が返した break のうち、**台帳の余剰が決済済ポジションで
> 過不足なく説明できるもの**を「booking 待ち（benign）」として break から外す。
> この判定を **mirror 窓の段階拡大より前**に置く（決済当日の窓拡大は必ず空振りするため）。
>
> 判定は **instrument 単位の数量合計**に限る。`closedpositions` は `OrderId` を
> 返さないため、個々の `trades` 行との 1対1 結合は行わない。
> 判断層 `trades` への価格書き戻しは引き続き人間が確認して行う（ADR-030 を維持）。
>
> あわせて、**台帳に未計上の決済を名指しする**層を足す（issue#20 の同日往復の死角）。
> 3層すべてがゼロで一致する状況でも「✓ 差分なし」と**断言しない**。

実装:
- `SaxoClient.get_closed_positions()` → `ClosedPosition`（`src/saxo_client.py`）
- `explain_ledger_surplus_by_closed_positions()`（`src/account_ledger.py`、DB 非依存の純関数）
- `SenseiDB.find_unbooked_closures()`（台帳に無い決済脚を指紋照合で検出）
- `scripts/sync_saxo.py` の `_drop_booking_pending()` が窓拡大の前段で呼ぶ
- field 定義: `docs/api/saxo/closed-position-fields.md`（ADR-026）

### 同日往復の死角（issue#20）

建てて同日に決済すると、`positions/me` も `orders/me` も空になり、`reports/trades` は
booking 遅延で未計上のため、**台帳 net も `trades` 申告も 0 で一致**する。
3層照合はこれを「差分なし」と報告するが、実際には未記録の往復が存在する
（🔬 2026-08-03 の SOXL 4株往復で発生。issue#23 として未記録のまま残っている）。

`closedpositions` にはその決済が現れるので、台帳に対応する決済脚が無いものを
`ℹ [未計上]` として報告し、最終行を `✓ break なし (ただし未計上の決済 N件)` に変える。
`OrderId` が無いため突合は **(instrument, side, quantity, price) の指紋**で行う。

## Rationale

**なぜ台帳に書かないか**: `closedpositions` は `OrderId` を返さない。
`account_transactions` の upsert キーは `broker_ref` であり、キーを作れない行を
混ぜると booking 到着時に同じ約定が二重計上される。また本 endpoint は
**全履歴を返さない**（🔬 2026-08-20 実測: `__count=2` で 8/19 分のみ。台帳にある
8/3 の往復は現れなかった）ため、そもそも台帳の代替にならない。

**なぜ窓拡大より前か**: 決済当日の欠落は「窓が狭い」ことに起因しない。
`reports/trades` にその行がまだ存在しない。窓拡大は API コールを4倍に増やすだけで
結果を変えない。安い1コール（closedpositions）で先に切り分けるのが正しい順序。

**なぜ過不足のない説明のみ benign にするか**: 部分的な一致で break を消すと、
booking 待ちに紛れた真の乖離が隠れる。説明しきれない差分は人間に見せる。

**副次的な価値**: `ClosedPosition` は `ProfitLossCurrencyConversion`（FX 変換損益）を
分離して返す。円口座 × USD 建 ETF では、これが価格変動損益とは独立したコスト源になる。
🔬 2026-08-19 の決済では損失 -¥60,916 のうち **-¥5,887（超過分の 84%）**がこの項で、
事前見積りとの差を「逆指値の滑り」と誤帰属していた（実際の約定は指値 $120.00 に対し
$120.03 で滑っていない）。ADR-029 の `cost_usd`（all-in 往復コスト）に対する
**事後の実績値**をこの層から取れる。

## Consequences

- **反映先**: `src/saxo_client.py` / `src/account_ledger.py` / `scripts/sync_saxo.py` /
  `docs/api/saxo/closed-position-fields.md` / `docs/api/saxo/endpoints.md` /
  `.claude/skills/sync-saxo/SKILL.md`
- **トレードオフ**: 照合層が3層→「3層＋説明層」になり、`/sync-saxo` の出力に
  `ℹ [booking待ち]` 行が増える。benign 判定は instrument 単位なので、
  同一 instrument で「booking 待ちの決済」と「真の mirror 漏れ」が同時に起きると
  数量が合わず両方 unexplained に落ちる（安全側に倒れる＝人間に見せる）。
- **`trades` の更新タイミングは変えない**: booking が到着し台帳に sell 行が入ってから
  `close_trade()` する運用を維持する。本 ADR は「照合が止まらない」ことだけを解決する。
- **見直しトリガー**:
  - Saxo が `closedpositions` に `OrderId` を追加したら、trades 行との 1対1 結合と
    当日クローズの自動化を再検討する
  - booking 遅延が T+1 を超えるケースを観測したら、benign 判定に経過時間の上限を入れる
    （現在は時間条件を課しておらず、いつまでも benign と判定しうる）
  - 保護脚（OCO の SL/TP）を独立 `trades` 行として起票する運用は本 ADR では変えていない。
    `[注文]` 層の break は残るため、その扱いは別途決める
