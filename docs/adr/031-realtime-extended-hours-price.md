# ADR-031: 延長時間リアルタイム価格の取得（プレ/アフター現値）

Status: accepted
Date: 2026-06-03

## Context

`/entry-analysis`（ADR-018）をはじめ価格・タイミングが絡む分析は、現値を **parquet（CacheManager）から読む**。parquet は Tiingo IEX 由来で **ET 09:30–15:55 のレギュラー時間のみ**（プレ/アフター 0 本、最大1日 stale）。`SaxoClient` も価格 quote 取得メソッドを持たず、entry-analysis では Saxo を「コスト・残高・建玉」にしか使っていない。

結果として、**プレ/アフター時間帯に分析すると現値がレギュラー前日終値で固定され、実勢を知らないまま判断を組み立てる**（推測の上に推測を重ねる）構造になっていた。これは繰り返し実害を出している:

- Session 41 / condition.md S37: dip-buy 指値 $228 が SOXL のプレマ大ギャップで現値 −13% に取り残され stale 化（OrderId 5409497457 未約定）。
- Session 35: yfinance prepost を**アドホック手動**で取得して判断に使用（5/27 プレマ $244.15 → $252.29）。再現性なし。
- Session 32: NVDA プレマ fade を判断材料化。

S37 line 127 に「進行中のプレマーケットはリアルタイム取得（yfinance/Tiingo）で補う」と明文化済みだが、**標準データ層（providers.py / update_data.py）は prepost を取得しておらず**、補完は毎回その場しのぎだった。

### 実測検証（2026-06-03 セッション、米プレマ 06:36 ET 時点）

| ソース | SOXL | 評価 |
|--------|------|------|
| parquet（現状 entry-analysis が読む） | $266.32（6/02 レギュラー終値・stale） | — |
| yfinance prepost（ライブ） | **$281.12**（06:35 ET） | ユーザー TradingView の「プレ 281.20（売り281.07/買い281.30）」と一致。実勢を正確に反映 |
| Tiingo IEX afterHours（ライブ・6/03 早朝） | **0 バー** | 早朝プレマ（04:00–08:00 ET）は未カバー |
| Tiingo IEX afterHours（6/02 完了分） | pre 18本（08:00–09:25 ET）/ post 31本（–16:55 ET） | **実トレード**だが窓が ~08:00–16:55 ET に限定・薄い |

追加検証 — 「6/02 の最安値」:

| 範囲 | 最安値 | ソース一致 |
|------|--------|-----------|
| レギュラー（09:30–16:00 ET） | **$238.82** | parquet $238.82 / Tiingo $238.91 / yfinance $238.82 |
| 延長込み | **$223.39**（04:00 ET プレマ） | yfinance のみ捕捉（Tiingo は 08:00 ET 以降で $238.91 止まり） |

→ レギュラー安値だけ見ると実際の延長安値より **$15・6.4% 高い**。逆指値/GTC の約定可否を誤判定する（S37 の穴の実証）。

判明した本質:
- **yfinance prepost の価格は正確**（TradingView と一致、6/02 重複窓で Tiingo 実トレードとも ~$243 で一致）。`vol=0` は「プレマバーに出来高を載せない yfinance 仕様」であって価格不正確を意味しない。
- **Tiingo afterHours は実トレードだが窓が狭い**（~08:00–16:55 ET）。早朝プレマ・深夜アフターは穴。
- **Saxo はマーケットデータ未購読**（condition.md S35: `PriceTypeBid/Ask: NoAccess`、`LastUpdated: 0001-01-01`、休場時 `CurrentPrice=0`）。リアルタイム価格には**有料購読が必要**＝実装でなく課金判断。なお購読が無くても**発注・約定は正常**で、約定価格は事後に `account_transactions`（ADR-030）で正確に取れる。穴は「分析インプットの鮮度」のみ。

froth の正しい扱い: プレマは薄商いで**寄りまで値が持たない可能性**がある（S37 / K-041）。これは「数字が嘘」ではなく「値動きの性質」であり、現値表示の信頼性とは別問題。sizing 判断に織り込む対象。

## Options

| 選択肢 | 長所 | 短所 | 採否 |
|--------|------|------|------|
| A. yfinance prepost を主とする on-demand 現値ヘルパー | 無料・検証済（TradingView 一致）・時間カバー最広（早朝〜深夜）・即実装可 | `vol=0` で出来高不明・非公式 API（仕様変更/停止リスク）・約定板そのものではない | **採用（主）** |
| B. Tiingo IEX afterHours を裏取りに併用 | 既課金（松）・**実トレード**で froth 判定の基準になる | 窓が ~08:00–16:55 ET に限定・早朝/深夜は空振り・IEX 薄い | **採用（補助・取得可能時間帯のみ）** |
| C. Saxo InfoPrices（`/trade/v1/prices/`） | 約定板そのもの・既認証 | **NoAccess（市場データ未購読）＝有料購読が必要**・休場時 0 | **不採用（当面）** |
| D. 延長バーを parquet に永続化 | 既存パイプラインに乗る | froth データがレギュラー系列を汚染・レジーム/分析の入力を歪める・薄商いノイズ蓄積 | **不採用** |
| E. 現状維持（手動 or 無し） | ビルド 0 | 毎回アドホック・非再現・stale 現値での推測継続（実害が出ている） | **不採用** |

## Decision

> **延長時間（プレ/アフター）の現値を on-demand で取得する薄いヘルパーを新設する。yfinance prepost を主ソース、Tiingo IEX afterHours を取得可能時間帯（~08:00–16:55 ET）の実トレード裏取りとして併用する。parquet には永続化しない。Saxo InfoPrices は市場データ未購読（NoAccess）のため当面採用しない。**

### 取得インタフェース（意味的アクセサ、ADR-026 準拠）

```python
@dataclass
class RealtimeQuote:
    symbol: str
    price: float                 # 現値（yfinance prepost の最新バー close）
    fetched_at: datetime         # 取得時刻（JST, aware）
    bar_time_et: datetime        # 価格バーの時刻（ET）
    regular_close: float         # 直近レギュラー終値（parquet）
    delta_pct: float             # regular_close からの乖離%
    session: str                 # 'pre' | 'regular' | 'post' | 'closed'
    confirm_source: Optional[str] # 'tiingo_iex' if 実トレードで裏取り可、else None
    confirm_price: Optional[float]
    is_thin: bool                # 薄商い注意（vol=0 / 早朝プレマ / 裏取り不能）
```

### 提示規律（必須）

1. プレ/アフター時間帯に価格・タイミングが絡む分析をする時は、**まず `RealtimeQuote` を取得し「現値・乖離%・取得時刻・session」を提示してから**分析に入る。stale parquet を黙って現値扱いしない。
2. froth は「**寄りまで持たない可能性**」として sizing 判断に注記する（S37 / K-041）。`is_thin=True` の値を sizing・stop の基準アンカーにしない。
3. 実約定の確定は `account_transactions`（ADR-030）で裏取りする。延長安値/高値での「約定した/しない」を現値ヘルパー単独で断定しない。

### 実装ノート（調査裏付け）

- **取得方法**: yfinance は `Ticker.history(period="1d", interval="1m", prepost=True)` の**最終バー `Close`** を現値とする。`fast_info.last_price` は使わない（本セッション実測で $266.32＝レギュラー終値を返し、プレマ $281 を反映しなかった）。データは UTC 返却のため ET に変換する（既存 tiingo_client と同様）。
- **薄商い判定 `is_thin`**（確立手法に準拠: Databento / softhints）: 以下のいずれかで `True`。
  - プレマ早朝（< 07:00 ET 目安、IEX 実トレード裏取り不能の時間帯）
  - 出来高が取れない（yfinance prepost は `vol=0` 固定）かつ Tiingo 裏取り不可
  - 一般原則「片側板が空 → null 価格」「mid でなく trade price を優先」「スプレッドが締まる/一定時間経過まで信用しない」
- **モジュール配置**: 既存 `ProviderChain`（`fetch_series(series, start, end)` で**履歴**を返す macro 用）には載せない。realtime は「現在の1スナップショット」で形が異なるため、**Protocol + fallback の*イディオムのみ*流用した別モジュール** `src/realtime.py` に置く。fallback 順は yfinance（主）→ Tiingo afterHours（取得可能時間帯）。
- **市場セッション判定**: 軽量な ET 時刻ベース（pre 04:00–09:30 / regular 09:30–16:00 / post 16:00–20:00 / closed）。祝日・半日は当面スコープ外（将来 `pandas_market_calendars` を検討）。既存ハードコード（signal_defs.py の 9:30、research_utils.py の定数）と矛盾しない定義にする。
- **テスト**: Tiingo（生 `requests`）は `responses` で HTTP mock、yfinance（ライブラリ）は `yf.Ticker` を monkeypatch / Fake で差し替え。testing-guidelines.md（ADR-022）の4層（既知解/境界/不変量/反例）に従い、特に「延長安値が regular 安値より低い」ケース（6/02 の $223.39 < $238.82）を境界テストに含める。

### スコープ外

- parquet スキーマ変更なし（延長バーは保存しない）。
- Saxo 市場データ購読は本 ADR の対象外（将来の課金判断）。
- 祝日・半日立会いの市場カレンダー（将来トリガーで `pandas_market_calendars` 導入）。
- ストリーミング/WebSocket リアルタイム（Intrinio/Databento 等の有料）。on-demand pull で十分。

## Rationale

- **正確性の実証**: yfinance prepost = TradingView（ユーザー常用）と一致、かつ 6/02 重複窓で Tiingo 実トレードと一致。主ソースとして信頼できる。一般的にも `prepost=True` + `interval=1m` が拡張時間取得の標準手法（複数の実装記事・ライブラリ `yfinance-extended` が同方式）。
- **手法調査の裏付け**: 拡張時間データは「片側板が空で null 化しやすい」「mid でなく trade price を使う」「スプレッドが締まる/時間経過まで信用しない」が定石（Databento 等）。本 ADR の `is_thin` と froth 規律はこの定石に沿う。ストリーミング API（Intrinio/Databento）は有料かつ overkill で、on-demand pull を採る。
- **コスト**: yfinance / Tiingo とも追加課金なし。Saxo は購読課金が必要で、現状の取引頻度・サイズに対し費用対効果が立たない（発注・約定は購読なしで成立し、約定価格は事後取得可能）。
- **責務分離（ADR-001）**: froth を含む延長バーを parquet に混ぜない。レギュラー系列（レジーム/分析の入力）の純度を保つ。
- **「事実と推測の分離」（CLAUDE.md）**: 「なぜこの数字か」を分解するには、まず実勢という事実が要る。stale 現値での推測継続を構造的に排除する。

## Consequences

- 反映先:
  - 新規 `src/realtime.py` に `get_realtime_quote(symbol) -> RealtimeQuote` を実装（macro ProviderChain とは独立、fallback イディオムのみ流用）。TDD（テスト先行）。
  - `/entry-analysis` SKILL: 現値取得ステップを正式化（プレ/アフター時は `RealtimeQuote` 提示を前段に追加）。
  - condition.md: 運用ルールを1行追記（プレ/アフター分析時は実勢取得を前提）。
  - CLAUDE.md「会話中の行動ルール」: stale 現値での推測継続を禁止する旨を追記候補。
- トレードオフ:
  - yfinance 非公式 API 依存。仕様変更/停止時は Tiingo（取得可能時間帯）+ 手動にフォールバック。
  - `vol=0` で出来高が取れず、薄商い判定は「早朝プレマ/裏取り不能」をプロキシにする。
- 将来の見直しトリガー:
  - プレ/アフター発注が常態化し、froth による fill 乖離が実損を出す → Saxo 市場データ購読（InfoPrices）を再評価し本 ADR を supersede。
  - yfinance が継続的に不安定 → Tiingo realtime / 別ソースへ主従入れ替え。
