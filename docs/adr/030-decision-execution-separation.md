# ADR-030: 判断層と執行事実層の分離 + Saxo 照合

Status: accepted
Date: 2026-06-03

## Context

Session（2026-06-03）で、`trades` テーブルが Saxo の実態と乖離していることが判明した:

- `trades` #12（SOXL long @218×3、`status='filled'`）は Saxo では 2026-06-02 09:30 ET に @243.18 で**クローズ済み**（+$75.54）だが、DB は建玉中のまま。
- `trades` #13（SOXL long @208×4、`status='placed'`）は、実際に Saxo で生きている注文が **5株 @228 GTC**（OrderId 5409497457）であり、価格も数量も一致しない（ブローカーで改定されたが DB 未更新）。

再認証して新トークンで取得しても Saxo 側の数字は1円も変わらなかった。**乖離の原因はトークンでも API でもなく、DB 側の構造**にある。

### 根本原因

`trades` は ADR-015 以来、本来分離すべき4つの関心を1行に圧縮している:

1. **宣言（intent / order）** — 何をどの価格・数量で出すか。可変（ブローカーで改定・取消）。
2. **執行事実（execution / fill）** — 実際に約定した不変の事実。
3. **損益（round-trip P&L）** — 約定をペアにした成績。
4. **判断（decision / reasoning）** — MAP 分析・レジーム・確信度・setup。Master Sensei の固有価値。

ADR-027 はこの歪みを明文で認識していた（line 79「`trades` が決定と執行を1テーブルで兼ねる歪みは残る」、line 80「placed→filled を Saxo API 約定確認と自動同期する仕組みは将来検討」）。今がその「将来」である。

さらに ADR-015 が設計した生データ層 `account_transactions`（口座の事実を記録する層）は「Saxo Excel インポートは将来タスク」のまま**一度も実装されていない**（ディレクトリも参照もゼロ）。結果、事実層が空のまま `trades` が全関心を1人で背負い、**事実層を手で書く → ブローカーと同期しない → drift** という構造になっていた。

### ベンチマーク調査

FIX プロトコル / 取引ジャーナル（Tradervue・TraderSync）/ OMS / イベントソーシング・投資照合の4方向を調査した結果、業界は普遍的に**同じ層分離**に収束していた:

| 層 | 役割 | 性質 | 出典概念 |
|----|------|------|---------|
| Order（宣言） | 注文＝意図 | 可変。ライフサイクル status（New→PartiallyFilled→Filled/Canceled/Replaced/Expired）。一意 ID = ClOrdId | FIX OrdStatus |
| Execution/Fill（事実） | 約定イベント | 不変・append-only 台帳。部分約定ごと1件。訂正は逆仕訳で追記 | FIX ExecutionReport / event sourcing |
| Position（導出） | 純保有 | execution の集計。保存せず都度計算 | — |
| Trade=round-trip（導出） | 損益単位 | execution のグループ化。分割・結合可能 | Tradervue / TraderSync |

**核心原則: 業界は「事実層を手で書かない」。** 常にブローカー明細（外部 SoT）からインポート/同期し、ポジションと成績は導出する。内部台帳 vs ブローカー明細を突合し、不一致を「**break**」として投資して解消する。結合キーは broker_ref（OrderId/ExecId）。

Master Sensei は ADR-025 で Saxo Live API を導入済みであり、**Saxo 自身が既にブローカー明細＝外部 SoT** になっている（`orders/me`=Order 層、`closedpositions/me`=round-trip、`positions/me`=Position）。ADR-015 が想定した「手動 Excel インポート」は **API pull で置換できる**状態にある。

## Decision

`trades` を**判断層に純化**し、執行事実は **Saxo 由来の `account_transactions`（生データ層）から導出**する。3層構成にする。

### 層構成

```
判断層  trades (DuckDB)          ← Sensei の固有価値（宣言・判断）
  MAP・regime・confidence・setup・planned entry/stop/size
  status(plan)・broker_ref ←この列で執行事実層と結合
  不変・後知恵バイアス排除はそのまま（ADR-018）
        ↕ broker_ref で結合・照合（break 検出）
執行事実層  account_transactions (Parquet)   ← ADR-015 の層を実装
  buy/sell/deposit/withdrawal の不変・append-only 台帳
  供給源 = Saxo Historical Report Data（手動 Excel ではない）
  運用 = 全 mirror 再取得 → ファイル上書き（価格/マクロと同じ）
        ↓ 集計して都度算出（保存しない）
導出ビュー（非永続）
  現ポジション・round-trip P&L・勝率・エクイティカーブ
```

### 1. 判断層 `trades`（DuckDB、純化）

- `trades` は「宣言・判断の記録」とする。MAP 分析・レジームスナップショット・確信度・setup・計画値（entry/stop/size）・`status`（plan の結末）を持つ。
- **`broker_ref` 列を追加**する（VARCHAR、nullable）。**Saxo の `OrderId` を格納**し、執行事実層との結合キーにする。これが**どの照合でも土台**になる。
  - Saxo には別名前空間の ID が3系統ある（**`OrderId`**=注文 / `TradeId`=約定 / `PositionId`=ポジション）。`OrderId` は `orders/me` と `reports/trades` の**両方が持つ唯一の共通キー**なので、判断/宣言（1注文）の粒度に一致する。`account_transactions` 側は約定単位の `TradeId` を主キーに持ち、`OrderId` で `trades` に join する。詳細: [docs/api/saxo/trade-report-fields.md](../api/saxo/trade-report-fields.md)。
  - ⚠ `closedpositions/me` の `PositionId` は別物。broker_ref に使わない。
- 既存の `entry_price`/`exit_price`/`pnl_usd` 等は後方互換のため残すが、**実約定の SoT は執行事実層**とする。`trades` の価格は「計画/記録時点の値」であり、実約定との差分は照合で検出する。
- 物理削除はしない（ADR-018 後知恵バイアス排除・ADR-027 と整合）。

### 2. 執行事実層 `account_transactions`（Parquet、ADR-015 を実装）

- 格納先は **Parquet**（`data/parquet/account/transactions.parquet`）。根拠: ADR-009/014「生データ(Raw)は Parquet に一本化」。`account_transactions` はブローカーの**事実**＝生データであり、自分の判断ではない。
- 行更新は不要。事実層は **Saxo から全 mirror 再取得して上書き**する（価格/マクロと同じ「再 fetch → 上書き」運用）。DuckDB が要るのは自分の判断の後日更新（predictions outcome, knowledge status）だが、事実層にその必要はない。
- スキーマは ADR-015 のものを踏襲し、**`broker_ref`（Saxo TradeId）を結合キー**として明示する。
- DuckDB の `trades` からは `read_parquet()` で透過 JOIN して照合する（ADR-001）。

#### 供給源（Saxo Historical Report Data）

| account_transactions の type | Saxo エンドポイント |
|------|------|
| buy / sell（約定明細） | `/cs/v1/reports/trades/{ClientKey}`（TradeId・日付範囲） |
| deposit / withdrawal（入出金） | Account Statement / Transaction 系レポート |
| （round-trip 成績の導出補助） | `/port/v1/closedpositions/me`（動作確認済） |

**フィールド定義は ADR-026 に従い、実装時に公式仕様で確認してから `docs/api/saxo/` に追記する**（推測禁止）。`/cs/v1/reports/trades/` と入出金レポートは未検証のため、実装前に endpoint 存在・契約状態・フィールドを確認する。

### 3. 導出ビュー（非永続、ADR-015 原則に回帰）

ポジション一覧・round-trip P&L・勝率・エクイティカーブは**保存せず都度算出**する（ADR-015 line141-148 の非永続原則）。

- **今の保有・生きてる注文** = Saxo API（`positions/me`・`orders/me`）を都度クエリ（ephemeral）。
- **過去の実現損益・コストベース・成績** = `account_transactions`（永続 mirror）から集計。Saxo API の履歴遡及には期間制限があるため、自前の不変台帳が必要。

### 4. 照合（reconciliation / break 検出）

`trades`（placed/filled）と執行事実層を `broker_ref` で突合し、不一致を **break** として列挙する。

| break の種類 | 条件 | 既定アクション |
|------|------|------|
| 宣言したが約定せず | `status='placed'` だが対応する fill が無く、対応 order も無い | 人間に提示（cancel/expire 候補） |
| 約定したが DB 未反映（クローズ） | `status='filled' AND exit_date IS NULL` だが closing fill が存在 | 提示 → `close_trade()` 候補 |
| 約定したが宣言なし | fill が存在するが対応する `trades` 行が無い | 人間に提示（手動エントリーの起票候補） |
| 注文が改定された | `status='placed'` の価格/数量が live order と不一致 | 提示（broker_ref 紐付け・値更新候補） |

- **曖昧でない遷移のみ自動更新**（matched fill による placed→filled、closing fill による filled→closed）。曖昧なものは人間に委ねる（後知恵バイアス・誤同期を避ける）。
- 実装形態は `/sync-saxo`（Skill）。SessionStart フックは「未照合 break あり」を状態注入して気付けるようにする（ADR-007/008）。

## Implementation

TDD（ADR 記録 → テスト → 実装）で段階的に進める。

### Phase 1: 土台（broker_ref）
- `src/db.py`: `trades` DDL に `broker_ref VARCHAR` 追加 + ADR-020 方式マイグレーション（既存 DB に `ALTER TABLE`、既存行は NULL）。
- `add_trade(..., broker_ref=None)` / `update_trade_status` に broker_ref 設定経路を追加。
- `tests/test_db.py`: broker_ref の追加・マイグレーション・後方互換テスト。

### Phase 2: 既存2行の整合（今回の drift 修正）
- #12 → `close_trade(12, exit_date=2026-06-02, exit_price=243.18, ...)` + broker_ref（closedposition の TradeId）。
- #13 → live order（5株 @228, OrderId 5409497457）と整合。値改定を反映し broker_ref=5409497457 を紐付け（または旧宣言を cancelled にし新規起票）。実装時にユーザーへ1件ずつ確認。

### Phase 3: 執行事実層の実装
- `docs/api/saxo/` に `/cs/v1/reports/trades/` 等のフィールド定義を公式仕様確認の上で追記（ADR-026）。
- `SaxoClient` に意味的アクセサ（reports/trades, account statement）を追加（raw dict 露出禁止、ADR-026）。
- `scripts/import_account_transactions.py`: Saxo から全 mirror 取得 → `data/parquet/account/transactions.parquet` に上書き。
- `SenseiDB` に導出ビュー（`read_parquet()` 経由のポジション・成績クエリ）。

### Phase 4: 照合機構
- `.claude/skills/sync-saxo/SKILL.md`: pull → mirror → diff → break 提示 → 自動/手動更新。
- SessionStart フック（`scripts/`）に未照合 break の状態注入。

### 変更ファイル（想定）
- `src/db.py`, `src/saxo_client.py`, `tests/test_db.py`, `tests/test_saxo_client.py`
- `scripts/import_account_transactions.py`（新規）, SessionStart フック
- `.claude/skills/sync-saxo/`（新規）, `.claude/skills/entry-analysis/SKILL.md`（broker_ref 起票指針）
- `docs/api/saxo/`（reports フィールド）, `CLAUDE.md`（trades の役割・照合運用）, `docs/adr/015`,`027`（本 ADR への参照追記）

## Consequences

- **drift が構造的に止まる**: 事実層を手で書かなくなり、`trades` は宣言だけを持つ。約定可否は Saxo 由来の `account_transactions` が答え、両者を broker_ref で突合して break を出す。
- ADR-015 の `account_transactions`（生データ層）が、供給源を Excel→Saxo API に変えて**今度こそ実装される**。
- ADR-027 が明記した「決定と執行の歪み」が解消される。
- 成績集計（勝率・P&L・エクイティ）は**導出**になり、保存しない（ADR-015 原則に回帰）。`status='filled'` フィルタ依存から、執行事実層ベースの集計へ移行。
- `trades` の `entry_price`/`pnl_usd` 等は「記録時点の計画/値」へ意味が変わる。実約定との差は照合で可視化。
- ADR-026 に従い Saxo reports 系のフィールドを公式確認・文書化する追加作業が発生する。
- 見直しトリガー: 部分約定・ナンピン・段階利確が頻発したら、ADR-015 line159 が予見した `executions` 子テーブル（フル正規化）への移行を別 ADR で検討する。現在の取引粒度（数株・単発）では Parquet 全 mirror で足りる。

### 同期の方針: トリガー駆動を採用（自動同期は不採用）

2026-06-03 の議論で、SessionStart フックによる**自動 mirror** および照合の**自動 self-heal**（曖昧でない status 遷移の自動適用）を検討したが、**不採用**とした。

- 理由: 判断ログ `trades` を機械が自動書き換えすると、マッチング誤りで**後知恵バイアス排除のための判断記録を静かに汚染**しうる（ADR-018）。人間が間に入る方が安全。
- 採用: **きっかけがあった時に `/sync-saxo` を明示実行**する trigger 駆動。残るのはミラーの鮮度ラグのみ（これは "drift" ではなく "古さ"）で、必要十分。
- したがって Phase4 の「SessionStart フックで break を自動注入/自動同期」は **将来タスクではなく、意図的に行わない**。再検討する場合は本 ADR を update してから。
