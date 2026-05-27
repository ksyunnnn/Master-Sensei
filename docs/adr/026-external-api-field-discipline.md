# ADR-026: 外部 API field 解釈の規律

Status: proposed
Date: 2026-05-26

## Context

2026-05-26 のセッションで、Saxo OpenAPI の Portfolio/Balances レスポンスを解釈する際、Master Sensei が **`CashBalance` フィールドを「取引可能額」だと変数名から推測** し、ユーザに「T126816 の今夜使える現金は $96 のみ」と誤った報告を行った。

実際の事実 (公式 schema 参照):
- `CashBalance: 15,216 JPY` (settled cash balance)
- `CashAvailableForTrading: 103,099 JPY` (取引可能額、broker 仕様で未決済込み)
- `SpendingPower: 103,099 JPY` (同上)
- `TransactionsNotBooked: 87,882 JPY` (T+2 未決済分)

→ 正しい usable cash は **$96 ではなく $649** であり、SOXL 3株まで追加可能。誤情報を実トレード判断に反映した場合、機会損失または不適切な position sizing につながる致命的誤り。

### 根本原因

- 外部 API レスポンスのフィールド意味を **公式 spec で確認せず、英語の変数名から推測** した
- 同一レスポンス内に類似名の field (`CashBalance` vs `CashAvailableForTrading` vs `SpendingPower`) が複数存在することを認識せず、最初に目に入った値を採用
- 解釈の根拠 (citation) を示さずに数値を提示
- ユーザに「何を根拠に？」と問われるまで誤りに気付かなかった

### 既存の整合性

CLAUDE.md は既に以下を定めている:
- 「事実と推測は分離。推測には確信度(%)を付与」
- 「設計判断や分析の提案前に十分な調査と根拠を提示する。直感で提案しない」

しかし **外部 API field の意味解釈** はこれら原則の盲点だった。「直感で提案しない」が API field level まで適用されていなかった。

### 規模

本プロジェクトは複数の外部 API に依存:
- 既存: FRED (`src/fred_client.py`), Tiingo (`src/tiingo_client.py`), yfinance, Saxo (`src/saxo_client.py` 新規)
- 計画中: Polygon, 他 broker, news API 等

→ Saxo 固有の対症療法では同種ミスが他 provider で再発する。**規律として一般化** する必要がある。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A. 現状維持 (CLAUDE.md「事実と推測の分離」原則のみ) | 追加コストゼロ | API field level の盲点が残る、同種ミス再発確実 | 不採用 |
| **B. provider 別 doc + コード規約 + CLAUDE.md ルール** | 構造的に推測を抑止、provider 追加が機械的 | 初期文書化コスト | **採用** |
| C. 自動化 skill (`/api-field-check`) | 強制力強い | SoT 原則 (CLAUDE.md 既述) と矛盾、過剰自動化 | 不採用 |
| D. type generation (Saxo OpenAPI spec → pydantic) | 型安全、強制力最大 | Saxo OpenAPI spec が機械可読 form で公開されていない、メンテコスト | 不採用 (検討候補として保留) |

## Decision

> **Option B (provider 別 doc + コード規約 + CLAUDE.md ルール) を採用する。** 以下を実施する:
>
> 1. **`docs/api/` ディレクトリ構造を新設する:**
>    ```
>    docs/api/
>    ├── README.md      # 全 provider index
>    ├── policy.md      # 本 ADR の運用ポリシー詳細
>    ├── TEMPLATE.md    # 新規 provider 追加時の雛形
>    └── <provider>/
>        ├── README.md
>        ├── <topic>.md
>        └── ...
>    ```
>
> 2. **provider doc の必須項目:**
>    - 各 field の公式定義 (出典 URL 必須)
>    - 「公式 doc にない」場合は明示 (推測しない)
>    - 「**本プロジェクトでこの用途に使うべき field はどれか**」の判断指針 (用途別の正解 field を表で示す)
>    - 実例レスポンス (PII マスク済み)
>
> 3. **コード規約 (`src/*_client.py` 全般に適用):**
>    - 外部 API レスポンスの **raw dict キー access を、client モジュール外部から行うことを禁止**
>    - client モジュール内に **意味的アクセサ** (e.g., `get_spending_power()`) を定義し、外部からはこれ経由のみアクセス
>    - 各意味的アクセサの docstring に `docs/api/<provider>/<file>.md#<field>` を citation
>    - raw dict を返す method (`get_balances()` 等) は残してよいが、docstring に「sizing 判断には `get_spending_power()` を使え」を明記
>
> 4. **CLAUDE.md に「外部 API 統合」セクション追加 (5行以内)** — 必読ルールと doc 所在を index。
>
> 5. **`docs/code-review-checklist.md` に項目追加** — レビュー時に raw dict 直 access を検出する。
>
> 6. **既存 provider (FRED, Tiingo, yfinance) の retroactive 文書化** は別タスク化。Saxo (本 ADR 起案の原因) は本日中に完全文書化。

## Rationale

### なぜ provider 別 doc か

- Claude Code 公式 best practice (`https://code.claude.com/docs/en/best-practices`) に「Give URLs for documentation and API references. Claude can read API docs — what it can't infer is your team's patterns」とある
- 公式 doc を丸ごとコピーしないが、**「team固有の用途別 field 選択」は明文化** が必要
- provider ごとにディレクトリを分けることで、新規 provider 追加が `TEMPLATE.md` をコピーするだけで済む

### なぜコード規約 (意味的アクセサ) か

- doc を読む規律だけでは「dict キーを直接書く」誘惑を構造的に防げない
- 意味的アクセサを必須にすることで、誤った field を選んだ瞬間にコード上で見える (PR review/grep で発見可能)
- 既存 `src/fred_client.py` `src/tiingo_client.py` は単一値 (`value`) を返す薄い wrapper なのでこの問題は表面化していないが、Saxo のように複数 field を返す API では essential

### なぜ自動化 skill ではないか

- CLAUDE.md「Memory運用ルール」「SoT はリポジトリ内」原則と整合
- 規律は人間が読める doc + コード規約で表現するのが本プロジェクトの設計思想
- 自動化は摩擦を上げる (skill 呼び出し忘れで形骸化)

### なぜ type generation (Option D) を保留か

- Saxo OpenAPI が機械可読 form で公開されている確証なし (developer portal は SPA で WebFetch では schema 取得困難)
- pydantic / dataclass 生成は強力だが、複数 provider それぞれ仕様取得方法が異なる
- 「provider が公式 OpenAPI/Swagger spec を提供している場合のみ」という条件で将来導入検討

## Charter Impact

- Charter 5.x「自己評価」: 「変数名から推測した」誤りを root_cause として認識し、構造的予防策を講じる原則を確立
- ADR-022「code-review-standards」の延長: 統計・金融コードレビュー基準に **外部 API field 解釈** を加える
- CLAUDE.md「事実と推測は分離」原則の **API field level への拡張**

## Consequences

### 反映先

- 新規ファイル:
  - `docs/api/README.md`
  - `docs/api/policy.md`
  - `docs/api/TEMPLATE.md`
  - `docs/api/saxo/README.md`
  - `docs/api/saxo/balance-fields.md`
  - `docs/api/saxo/endpoints.md`
  - `docs/api/saxo/rate-limits.md`
- 既存ファイル変更:
  - `src/saxo_client.py`: 意味的アクセサ追加 + raw dict method の docstring 更新
  - `tests/test_saxo_client.py`: 意味的アクセサのテスト追加
  - `CLAUDE.md`: 「外部 API 統合 (ADR-026)」セクション追加
  - `docs/code-review-checklist.md`: raw dict 直 access 禁止項目追加
  - `docs/adr/025-saxo-openapi-auth.md`: 本 ADR への cross-reference 追記

### トレードオフ

- 初期文書化コスト ~70分 (Saxo 1 provider 分)
- 各 provider 追加時に TEMPLATE に従う必要 (10-20分程度の overhead)
- 意味的アクセサ追加で client モジュールの行数増加 (許容範囲)

### 見直しトリガー

- **Saxo が公式 OpenAPI spec (JSON/YAML) を提供開始した場合** → Option D (type generation) 導入検討
- **provider 数が 10 を超え、TEMPLATE の更新負荷が高まった場合** → 共通 base class (`BaseAPIClient`) 導入検討
- **本ルール遵守違反が code review で複数回発見された場合** → 自動化検出 (lint rule 等) 導入検討

### 既存 provider への遡及適用

| Provider | 状態 | 対応 |
|----------|------|------|
| Saxo | 新規 (本 ADR 起案契機) | 本日中に完全文書化 + 意味的アクセサ |
| FRED | 既存、シリーズ単純 (`value` のみ) | 別タスク (TEMPLATE 適用、low priority) |
| Tiingo | 既存、daily/intraday 仕様あり | 別タスク (medium priority) |
| yfinance | 既存、unofficial wrapper | 別タスク (caveat 集として high priority) |

### 実装タイミング

- 設計確定: 本 ADR で 2026-05-26
- Saxo 実装: 本日中 (米寄り 22:30 JST までに完了させる)
- 既存 provider 遡及: 別セッションタスクとして登録
