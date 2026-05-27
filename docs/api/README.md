# 外部 API リファレンス index (ADR-026)

Master Sensei が依存する外部 API の公式仕様を集約。

## 必読ポリシー

- [policy.md](policy.md) — 推測禁止・citation 必須・raw dict 禁止の原則
- [TEMPLATE.md](TEMPLATE.md) — 新規 provider 追加時の雛形

## Provider 一覧

| Provider | code module | 用途 | doc 完成度 |
|----------|-------------|------|----------|
| [saxo/](saxo/README.md) | `src/saxo_client.py` | 口座残高・ポジション (OAuth, ADR-025) | ✅ 完全文書化 |
| fred/ (未作成) | `src/fred_client.py` | マクロ指標 9 シリーズ (FOMC, CPI 等) | ⏳ 別タスク |
| tiingo/ (未作成) | `src/tiingo_client.py` | 株価 daily / intraday | ⏳ 別タスク |
| yfinance/ (未作成) | `src/providers.py` (chain) | VIX, VIX3M, Brent 即時取得 | ⏳ 別タスク |

## 新規 provider 追加手順

1. `cp -r docs/api/saxo docs/api/<provider>` または `cp TEMPLATE.md docs/api/<provider>/README.md`
2. 公式 spec の URL を citation として埋めながら各 field を文書化
3. `src/<provider>_client.py` に意味的アクセサを実装 (raw dict 露出禁止)
4. 本 README の「Provider 一覧」表に追記
5. テスト追加 (アクセサごとに最低1 case)
