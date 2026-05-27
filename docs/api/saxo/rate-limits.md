# Saxo OpenAPI Rate Limits

**公式**: https://www.developer.saxo/openapi/learn/rate-limiting

## 制限値 (公式記載)

| Dimension | 上限 |
|-----------|-----|
| アプリ全体 | **10,000,000 req/日** (max number of requests per application across all users and sessions) |
| セッション × サービスグループ | **120 req/分** (max per session per service group) |
| 発注 (per session) | **1 req/秒** (only for orders) |

## 超過時

- HTTP **429 Too Many Requests** 返却
- Identical order operations が 15秒以内に来た場合は HTTP **409 Conflict** (unique `x-request-id` header で回避可能)

## レスポンスヘッダ

各レスポンスに含まれる:
- `X-RateLimit-<dimension>-Limit`
- `X-RateLimit-<dimension>-Remaining`
- `X-RateLimit-<dimension>-Reset`

`<dimension>` は AppDay, AppMinute, AccountMinute 等 (詳細は公式 doc)。

## 本プロジェクトでの実需要

1セッションで以下程度:
- `get_accounts()` 1 req
- `get_balances()` × 7 sub-accounts = 7 req
- `get_positions()` 1 req
- 合計 ~10 req

→ **120 req/分 の 10% 程度**、制限に対して 12倍の余裕。
→ 1日 1,000万 req 制限には到底届かない。

## SIM vs Live の差

公式 doc に記載なし。本プロジェクトは Live のみ使用。

## 注意点

- rate limit に近づいた場合、レスポンスヘッダ `X-RateLimit-*-Remaining` で残量を確認できる
- 現実装 (`src/saxo_client.py`) は rate limit ヘッダを利用していない。利用量が増えたら client 側で throttle 実装を検討
