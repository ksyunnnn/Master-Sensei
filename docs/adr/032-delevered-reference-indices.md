# ADR-032: de-levered 参照指数の追加（SOXX/SPY/QQQ/IWM、日足＋5分足）

Status: accepted
Date: 2026-06-17

## Context

セッション中、6/16 の半導体売りを評価する際、保有銘柄の SOXL（3x）の日中 −17% を
そのままセクターの強弱として語ると、レバレッジ分（約3倍）と日次リセットの path-decay で
**絶対値が誇張される**問題が顕在化した。「半導体が最弱」という相対順位は 3x 同士の比較で
正しいが、セクターの素の下落率を述べるには **原指数（1x）** を見る必要がある。

しかし収集ユニバースは取引対象のレバ ETF（TRADING_SYMBOLS 8本）＋ 低流動性参照
（VIXY/TECS、日足のみ）に限られ、原指数を保持していなかった。`signal_runner.py` には
SOXX/SPY/QQQ/IWM を参照に使う意図の痕跡があったが、Tiingo の fetch リスト
（`REFERENCE_SYMBOLS`）に未配線で、parquet は空だった。

ADR-004 の中核警告「**5分足は蓄積式。開始が遅れた分だけ過去データを失う（IEX 1リクエスト
≈128営業日）**」が今回も効く。「あの日の日中、原指数はどう動いたか」という後追いの問い
（イベント事後検証 /review-events、相対強度シグナル、知見形成）は実際に発生し、これは
**realtime 取得では答えられない**（realtime は「今」しか返さない）。貯め始めなかった日中
データは後から二度と取れない。

## Decision

de-levered 参照指数として **SOXX / SPY / QQQ / IWM** を追加する。**日足＋5分足の両方**を
蓄積する。これらは **取引しない**（ポジション・執行の対象外）。

シンボル定義（`src/tiingo_client.py`）を蓄積方針で分割:

| リスト | 銘柄 | 日足 | 5分足 |
|--------|------|:----:|:-----:|
| `TRADING_SYMBOLS` | TQQQ/SQQQ/SOXL/SOXS/TECL/SPXL/TNA/TZA | ✓ | ✓ |
| `REFERENCE_SYMBOLS_DAILY_ONLY` | VIXY/TECS | ✓ | — |
| `REFERENCE_SYMBOLS_INTRADAY` | **SOXX/SPY/QQQ/IWM** | ✓ | ✓ |

- `REFERENCE_SYMBOLS = DAILY_ONLY + INTRADAY`（日足ループ `TRADING + REFERENCE` は不変）
- `INTRADAY_SYMBOLS = TRADING_SYMBOLS + REFERENCE_SYMBOLS_INTRADAY`（5分足ループが走査）

各参照には売買する 3x 対応がある: SOXX→SOXL/SOXS, QQQ→TQQQ/SQQQ, SPY→SPXL, IWM→TNA/TZA。

## Rationale（なぜ 5分足も貯めるか）

1. **後追いの日中問いは realtime で代替できない**。realtime は「今」の現値のみ。過去日の
   日中再構成は蓄積した 5分足だけが可能で、かつ非可逆（貯めなければ失う）。
2. **VIXY/TECS の「日足のみ」前例は当てはまらない**。あれは ADR-004 で「出来高が低く
   5分足不要」が理由。SOXX/SPY/QQQ/IWM は市場最高流動性級で、この理由は逆に不成立。
3. **コストは無視できる**。parquet intraday は約 0.7MB/銘柄、+4 で約 +2.9MB。更新は
   +4 リクエスト/回（Free tier 50req/h に対し余裕）。DuckDB の肥大も中身は数 MB で問題なし。
4. **品質優先の原則**（松を目指す／逆引きでデータの将来価値を考える）。コストが無視できる
   以上、非可逆な選択肢を温存する。

## Consequences

- de-levered な原指数で「セクターの素の強弱」を日足・日中とも読めるようになり、3x の
  誇張・path-decay 補正を毎回手計算する必要がなくなる。
- 検証: 初回バックフィルで日足 各1,254本（5年）、5分足 各10,000本（IEX 上限≈128営業日）。
  6/15→6/16 の原指数下落は SOXX −5.92% / QQQ −1.90% / IWM −0.87% / SPY −0.60% と確定し、
  「risk_on だが半導体最弱」を 1x 解像度で裏取りした（SOXL −17% ÷3 ≈ −5.7% と整合）。
- これらは取引対象ではない。サイジング・予測・trades の対象に含めない。

## 再検討トリガー

- セクターの**日中乖離を頻繁に使う戦略**が実証され、より長い 5分足履歴が必要になった場合
  → 蓄積継続の優先度を上げる／追加銘柄を検討。
- 参照指数を使った相対強度シグナルが定着した場合 → ADR-004 のシンボル選定基準に統合。

## 関連

- ADR-002（データソース選定）、ADR-004（銘柄選定基準・蓄積式の制約）
- ADR-031（realtime 延長時間価格＝「今」の取得。本 ADR は「過去日中」を補完する関係）
