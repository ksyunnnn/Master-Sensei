# API制約サマリー

各APIの詳細はADRを参照。ここは運用時のクイックリファレンス。

## Tiingo (価格OHLCV)

- **契約プラン: Power $30/mo (ADR-002)** → 10,000 req/時間, 100,000 req/日, 40GB/月
  - (参考) 無料 STARTER は 50 req/時間, 1,000 req/日, 500 symbols/月
- 現在の消費: ~26 req/実行（日足14 + 5分足12）。マクロは yfinance/FRED 経由で Tiingo を使わない
  - 2回目以降の同日 run は日足スキップ(`end_date>=today`)で 5分足12 のみ
- IEX上限: 10,000 points/req（2026-03-26実測）
- レート制限: 公式に「秒/分制限・同時実行制限なし」→ fetch を ThreadPool(8) 並列化(update_data.py)。
  自前の2s throttle は無効化。429 リトライ(60秒)は維持
- 詳細: docs/api/tiingo/rate-limits.md（公式値・出典）, ADR-002, ADR-004

## FRED (マクロ指標 公式)

- 120 req/分。9シリーズで制限に対して十分余裕
- 公開遅延: 1-2日（シリーズによる）
- 詳細: ADR-002

## yfinance (マクロ指標 即時)

- 非公式API。レート制限は非公開（~2,000 req/時間の報告あり）
- 対応: VIX(^VIX), VIX3M(^VIX3M), Brent(BZ=F)
- FREDの遅延を補完。ProviderChainでフォールバック
- 詳細: ADR-005, ADR-006
