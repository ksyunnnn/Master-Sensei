# 外部 API 統合ポリシー (ADR-026 詳細)

## 原則 3点

### 1. 推測禁止 (variable-name inference 禁止)

外部 API レスポンスのフィールド意味を、英語の変数名から推測してはならない。

❌ 悪い例: 「`CashBalance` だから取引可能な現金だろう」
✅ 良い例: 「公式 schema doc では `CashBalance` = "Current cash balance" (settled cash only)、取引可能額は `CashAvailableForTrading` または `SpendingPower`」 (出典: https://www.developer.saxo/openapi/referencedocs/port/v1/balances/...)

### 2. citation 必須

各 field 説明には公式 doc の URL を必ず併記する。「公式 doc に記載なし」の場合は明示する (推測で補完しない)。

### 3. raw dict access 禁止 (code level)

外部 API レスポンスを `dict["FieldName"]` で直接読むコードを `src/*_client.py` の **外部** に書いてはならない。client モジュール内に意味的アクセサを定義し、外部からはこれ経由のみ。

## なぜこのポリシーか

2026-05-26 セッションで Saxo `CashBalance` を「取引可能額」と誤解釈し、ユーザに「$96 のみ」と報告。実際は `CashAvailableForTrading: $649` で 6.7倍 の乖離。トレード判断の根幹である position sizing を誤らせる致命的バグ。

詳細: [ADR-026](../adr/026-external-api-field-discipline.md) Context 節

## doc 配置規約

各 provider は `docs/api/<provider>/` に以下を持つ:

| ファイル | 内容 |
|---------|------|
| README.md | provider 概要、endpoint catalog、よく使う field の早見表 |
| `<topic>-fields.md` | 各 field の公式定義 + citation (例: `balance-fields.md`) |
| endpoints.md | 使用する endpoint 一覧 + 実例レスポンス (PII マスク) |
| rate-limits.md | rate limit 公式値 |
| auth.md | 認証フロー (該当する場合) |

公式 doc が SPA で WebFetch しづらい場合は **実際の API レスポンスを最小例として記録** する (response key の網羅性を担保)。

## コード規約

### 必須: 意味的アクセサ

```python
class SaxoClient:
    def get_spending_power(self, account_key: str) -> float:
        """口座の取引可能額 (SpendingPower、未決済込み)。

        See docs/api/saxo/balance-fields.md#spendingpower
        """
        return float(self._get_balance(account_key)["SpendingPower"])

    def get_settled_cash_balance(self, account_key: str) -> float:
        """settled cash のみ (CashBalance、会計表示用)。
        sizing 判断には get_spending_power() を使うこと。

        See docs/api/saxo/balance-fields.md#cashbalance
        """
        return float(self._get_balance(account_key)["CashBalance"])
```

### 許可: raw dict 取得 (調査用途のみ)

```python
def get_balances(self) -> dict:
    """raw レスポンス全体を返す。
    **sizing 判断には get_spending_power() / get_settled_cash_balance() を使うこと。**
    この method は schema 確認・新 field 発見等の調査用途のみ。

    See docs/api/saxo/balance-fields.md
    """
```

### 禁止: client 外部での dict キー access

```python
# ❌ 禁止
balances = client.get_balances()
cash = balances["CashBalance"]  # field 意味の推測リスク

# ✅ 推奨
cash = client.get_spending_power(account_key)
```

## レビュー時のチェックポイント

`docs/code-review-checklist.md` に追加:
- `src/*_client.py` 外部で `["FieldName"]` パターンの dict access がないか grep
- 新 endpoint 使用時、対応する意味的アクセサが追加されているか
- 各意味的アクセサに `docs/api/...` citation があるか
