# <Provider 名> API リファレンス

## 概要

- **公式 doc**: <URL>
- **code module**: `src/<provider>_client.py`
- **認証方式**: <e.g., OAuth 2.0 / API Key / なし>
- **rate limit**: <e.g., 50 req/hour、詳細は rate-limits.md>
- **本プロジェクトでの用途**: <e.g., 株価日足取得、レジーム判定用マクロ取得>

## ファイル

| ファイル | 内容 |
|---------|------|
| README.md | 本ファイル。概要 + 早見表 |
| <topic>-fields.md | レスポンス field の公式定義 (citation 必須) |
| endpoints.md | 使用 endpoint 一覧 + 実例レスポンス |
| rate-limits.md | rate limit 公式値 |
| auth.md | 認証フロー (該当時) |

## 用途別 field 早見表

**重要**: API レスポンスを解釈する前に必ず参照する。変数名からの推測禁止 (ADR-026)。

| 用途 | 使う field | 注意 |
|------|----------|------|
| <例: 新規取引の sizing> | <field 名> | <落とし穴があれば記載> |
| <例: 会計表示> | <field 名> | <別 field との混同注意> |

## 意味的アクセサ (src/<provider>_client.py)

| アクセサ | 返す field | 用途 |
|---------|----------|------|
| `<method>()` | `<FieldName>` | <用途> |

## 既知の落とし穴

- <例: field A と field B が似た名前だが意味が違う、公式 doc URL>
- <例: 環境 (SIM/Live) で挙動差があるなら明記>

## 参考リンク

- 公式 reference: <URL>
- glossary: <URL>
- changelog: <URL>
