# ADR-027: トレードの発注ライフサイクル（status 列）

Status: accepted
Date: 2026-05-29

## Context

Session 35 で、`trades` #11（SOXL long $215 GTC 指値 IFD-OCO）が**約定済みポジションとして残存**している問題が判明した。

- `/entry-analysis`（ADR-018）は後知恵バイアス排除のため**発注時点で `add_trade()` を呼ぶ**。#11 もこの規律に従い、発注時の MAP 分析を `entry_reasoning` に正しく記録していた。
- しかし $215 指値は不発に終わり（発注後セッション安値 $224.19、$215 未到達）、ユーザーが注文をキャンセルした。
- `trades` は ADR-015 で「約定した1ラウンドトリップ = 1行」「`entry_date`/`entry_price` NOT NULL（約定前提）」と設計されており、**「発注したが約定しなかった」を表現する状態が無い**。
- 結果、#11 は `exit_date IS NULL`＝「保有中ポジション」と区別がつかず、次セッション以降で「SOXL 1株保有」と誤認するリスクがあった。

### 検討した代替案

| 案 | 評価 |
|----|------|
| 物理削除（`delete_trade`） | **却下**。ADR-018 が発注時点で記録した「意思決定の事実」を捨てる。後知恵バイアス排除の目的に反する |
| `predictions` で代用 | **却下**。ADR-018 は entry-analysis からの予測自動起票を明示的にスコープ外化。order fill は市場予測ではなく Brier を汚す |
| `account_transactions`（生データ層）で吸収 | **不可**。約定事実のみを記録する層。不発・キャンセルは約定でないため載らない |
| decision 層を別テーブルに分離 | 設計的には最も綺麗だが重い。将来の選択肢として保留 |
| **`trades` に `status` 列を追加（採用）** | 軽量。意思決定の記録（`entry_reasoning`）を保持したまま、結末を表現できる |

## Decision

`trades` に発注ライフサイクルを表す `status` 列を追加する。

### status の値

| 値 | 意味 | P&L |
|----|------|-----|
| `placed` | 発注済み・約定待ち（resting limit / IFD-OCO 等） | なし |
| `filled` | 約定済み。実ポジション=ラウンドトリップの起点 | close 後に確定 |
| `cancelled` | 発注後に手動キャンセル（約定せず） | なし |
| `expired` | GTC 等が失効（約定せず） | なし |

- **デフォルトは `filled`**。後方互換のため: 既存の `add_trade()` 呼び出しと過去データは全て「実際にエントリーした取引」を表していた。
- `/entry-analysis` が resting 指値を発注時点で記録する場合は `status='placed'` を明示的に渡す。

### 統計・ポジション判定の規律

- **保有ポジション = `status='filled' AND exit_date IS NULL`**。`placed`/`cancelled`/`expired` はポジションではない。
- `get_open_trades()` はこの定義に変更する（従来の `exit_date IS NULL` のみは placed を誤って含む）。
- 未約定の発注一覧は `get_pending_orders()`（`status='placed'`）で取得する。
- 勝率・平均損益など成績集計は `status='filled'` のみを対象とする。

### マイグレーション（ADR-020 方式）

- 新規 DB: `CREATE TABLE` に `status VARCHAR NOT NULL DEFAULT 'filled'` を含める。
- 既存 DB: `information_schema.columns` で列の有無を確認し、無ければ `ALTER TABLE trades ADD COLUMN status VARCHAR DEFAULT 'filled'`。既存全行は `filled` にバックフィルされる（過去データは全て実約定だったため正しい）。
- 個別データ修正（#11 → `cancelled`）はマイグレーションではなく `update_trade_status()` の単発呼び出しで行う。

### 状態遷移

最小版では遷移ステートマシンは実装せず、`status` 値の集合バリデーションのみ行う（ADR-018 の複雑性バイアス回避方針を踏襲）。妥当な遷移は `placed → {filled, cancelled, expired}` だが、強制はしない。

## Implementation

### 変更ファイル
- `src/db.py`:
  - `trades` DDL に `status` 追加 + マイグレーション
  - `add_trade(..., status='filled')` — バリデーション + INSERT に追加
  - `update_trade_status(trade_id, status, *, notes=None)` — 新規
  - `get_open_trades()` — `status='filled' AND exit_date IS NULL` に変更
  - `get_pending_orders()` — 新規
- `tests/test_db.py` — 上記のテスト
- `.claude/skills/entry-analysis/SKILL.md` — resting 指値時の `status='placed'` 指針
- `CLAUDE.md` — 必要に応じて trades の Write 基準を補足

### データ修正
- `update_trade_status(11, 'cancelled', notes='$215 GTC IFD-OCO 不発→キャンセル。発注後安値 $224.19 で $215 未到達 (Session 35 確認)')`

## Consequences

- 「発注したが約定しなかった」意思決定が履歴として残る（ADR-018 の後知恵バイアス排除と整合）。
- placed 注文がポジションと誤認されなくなる（#11 問題の再発防止）。
- 成績集計は `status='filled'` フィルタが必須になる。
- `trades` が「決定」と「執行」を1テーブルで兼ねる歪みは残る。decision 層の完全分離が必要になった場合は別 ADR で対応する。
- 見直しトリガー: placed→filled の遷移を Saxo API 約定確認と自動同期する仕組みを将来検討（現状は手動 `update_trade_status`）。
