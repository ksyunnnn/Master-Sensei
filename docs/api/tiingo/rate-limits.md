# Tiingo レート制限（公式値）

- **公式 doc**: https://www.tiingo.com/documentation/general/overview （§1.1.3 Usage Limits）
- **pricing 表**: https://www.tiingo.com/about/pricing
- **取得日**: 2026-06-19（Playwright で描画後テーブルから確認）
- **code module**: `src/tiingo_client.py`

## 制限の種類（公式原文）

> To keep the API affordable to all, each account is given generous rate-limits. We limit based on:
> - **Hourly Requests** - Reset every hour.
> - **Daily Requests** - Reset every day at midnight EST.
> - **Monthly Bandwidth** - Reset the first of every month at midnight EST.
>
> **We do not rate limit to minute or second, so you are free to make your requests as you desire.**

→ **秒・分単位の制限／同時実行（concurrency）制限は存在しない**。制限は「時間あたり総数」「日あたり総数」「月帯域」の3つのみ。**並列バーストは公式に許容**される（リクエスト総数は逐次と同じなので時間/日のクォータ消費も同じ。並列化で増えるのは瞬間の同時接続数だけで、それは制限対象外）。

## プラン別の数値（pricing 表、2026-06-19）

| 項目 | STARTER（無料 $0） | POWER（$30/月・$300/年） |
|------|------------------|------------------------|
| Unique Symbols / 月 | 500 | 108,440 |
| **Max Requests / 時** | **50** | **10,000** |
| **Max Requests / 日** | **1,000** | **100,000** |
| Max Bandwidth / 月 | 1 GB | 40 GB |

## 429 応答時

時間/日のクォータ超過で `HTTP 429`。`src/tiingo_client.py` は 429 で 60s 待って 1 回だけ再試行する。

## 本プロジェクトでの消費量

`update_data.py` 1 回の実行で Tiingo を叩く回数 = **日足 14 銘柄 + 5分足 12 銘柄 = 26 リクエスト**（マクロは yfinance/FRED 経由で Tiingo を使わない）。

- **STARTER（50/時）の場合**: 26 req/run なので **1 時間に 1 回まで**が安全圏（2 回で 52 > 50 → 2 回目が 429 になりうる）。並列化しても総数は 26 のままなのでこの制約は不変（速くなるのは wall-clock のみ）。
- **POWER（10,000/時）の場合**: 26 は誤差。実質無制限。

> **設計上の含意**: 並列化はどちらのプランでも安全（秒/分制限なし・総数不変）。ただし STARTER では「1 時間に複数回の full update」を避ける運用注意が残る。これはレート設計でなく実行頻度の問題。
