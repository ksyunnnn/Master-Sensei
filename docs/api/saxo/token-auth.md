# Saxo OAuth token 仕様 (ADR-025 / ADR-026)

認証方式: **OAuth 2.0 Authorization Code grant**。token endpoint は Portfolio API とは別ホスト。

## token endpoint

```
POST https://live.logonvalidation.net/token        (live)
POST https://sim.logonvalidation.net/token         (sim)
```
- 用途: code 交換 (`grant_type=authorization_code`) ＋ refresh (`grant_type=refresh_token`)
- 認証: HTTP Basic (`app_key` / `app_secret`)
- 実装: `SaxoClient.exchange_code_for_tokens()` / `SaxoClient._refresh_access_token()`

## token lifetime（**固定の公式値は存在しない=app依存**）

| token | 公式の記載 | 当 LIVE アプリ実測 (2026-06) | 応答フィールド |
|-------|-----------|------------------------------|----------------|
| access  | **20分** (`expires_in: 1200`)。Saxo Support「typically kept short at 20 minutes」 | 20分 (1200s) | `expires_in` |
| refresh | doc 例では **40分** (`refresh_token_expires_in: 2400`) | **60分** (3600s) | `refresh_token_expires_in` |

- **重要**: Saxo 公式 Authorization Code Grant doc は「これらは**例**であり、実際の lifetime は
  **アプリ設定や Saxo のポリシーにより変わる**。確定値はアプリごとに Support に確認せよ」と明記。
  実際 **公式例(refresh 40分) と当アプリ実測(60分) は食い違う**＝app 依存の裏付け。
- → **コードは数字をハードコードしない**。`expires_in` / `refresh_token_expires_in`(=応答値)を
  `auth_tokens.expires_at` に保存し、それを読む(`SenseiDB.get_active_token`)。これが「推測なく準拠」。
- **ローリング(rotating)**: refresh のたびに **新 access ＋ 新 refresh** が返る(旧 refresh は単回使用で無効化)。

## 運用上の含意

- access(20分)失効は in-session `SaxoClient.get_access_token()` が on-demand で透過的に更新
  (`ACCESS_TOKEN_REFRESH_BUFFER_SEC=60` で失効間際に refresh)。**refresh token が生きていれば
  ブラウザ再認証は不要**。
- refresh token が失効(>lifetime 放置, 例: PC スリープ)すると `saxo_oauth_init.py` での
  **ブラウザ再認証**が必要(K: session43 PC スリープ教訓)。
- これを防ぐ backstop が `scripts/saxo_keepalive.py`: refresh の `expires_at` を読み、
  失効直前(margin)に1回だけ roll する(**access<refresh** なので roll 時 access は失効済→
  `get_access_token()` が rolling refresh を起こす)。**token 再発行は失効周期に1回=最小**。

Sources:
- [Saxo Support: access token kept short at 20 minutes](https://openapi.help.saxo/hc/en-us/articles/4416637029649-How-do-I-get-an-access-token-that-lasts-longer-than-the-24H-token)
- [Saxo Developer: OAuth Authorization Code Grant (expires_in 1200 / refresh_token_expires_in 2400 の例・app依存の但し書き)](https://www.developer.saxo/openapi/learn/oauth-authorization-code-grant)
