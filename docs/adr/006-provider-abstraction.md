# ADR-006: マクロデータプロバイダの抽象化（Protocol導入）

Status: accepted
Date: 2026-03-27

## Context

VIXのリアルタイム取得のため、FRED以外のデータプロバイダ（yfinance, Nasdaq Data Link）を追加する。
現在のコードは各プロバイダが独自のインターフェースを持ち、共通の抽象がない。
フォールバック（yfinance失敗→Nasdaq試行）を実装するには共通インターフェースが必要。

## Options

### A: 抽象化なし（個別実装）

| 長所 | 短所 |
|------|------|
| 初期コストゼロ | プロバイダ追加ごとにupdate_data.pyにif分岐追加 |
| | フォールバックがif/elseの条件分岐になり複雑化 |

### B: ABC（抽象基底クラス）

| 長所 | 短所 |
|------|------|
| 明示的なインターフェース | 既存クラス（FredClient）の継承変更が必要 |
| | Python的にはheavyweight |

### C: Protocol（PEP 544 構造的サブタイピング）

| 長所 | 短所 |
|------|------|
| 約10行で定義可能 | ランタイムの型チェックはない（静的解析用） |
| 既存クラスの変更不要 | |
| Adapterパターンと自然に組み合わせ可能 | |

## Decision

> **Option C: Protocolを導入する。**

### インターフェース定義

```python
class MacroProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    def fetch_series(
        self, series: str, start_date: date, end_date: date
    ) -> list[dict]:
        """[{"date": "YYYY-MM-DD", "value": float}, ...]"""
        ...

    def available_series(self) -> list[str]: ...
```

### プロバイダごとのシリーズ名マッピング

```python
SERIES_MAPPING = {
    "VIX":     {"fred": "VIXCLS",      "yfinance": "^VIX",   "nasdaq": "CBOE/VIX"},
    "VIX3M":   {"fred": "VXVCLS",      "yfinance": "^VIX3M", "nasdaq": None},
    "BRENT":   {"fred": "DCOILBRENTEU","yfinance": "BZ=F",   "nasdaq": None},
    ...
}
```

各Adapterが内部でマッピングを解決する。呼び出し側は統一シリーズ名（"VIX"等）を使う。

### フォールバック

```python
providers = [yfinance_provider, nasdaq_provider, fred_provider]
for provider in providers:
    if series in provider.available_series():
        try:
            return provider.fetch_series(series, start, end)
        except Exception:
            continue
```

速度順（yfinance→Nasdaq→FRED）に試行し、成功したら終了。

## Rationale

- **YAGNI例外**: プロバイダ追加は「推測」ではなく「確定要件」（Fowler: "when the presumptive feature is justified")
- **Rule of Three**: FRED(1) + yfinance(2) + Nasdaq(3) で抽象化の閾値に到達
- **PEP 544 Protocol**: 既存のFredClientを変更せずにAdapterで適合させられる（構造的サブタイピング）
- **backtest側との対比**: backtest/tools/update_cache.pyはTiingo1社のみで抽象化不要。master_senseiは3プロバイダで状況が異なる

### 避けること

- ファクトリパターン / プロバイダレジストリ → 3個程度ではオーバーエンジニアリング
- 深い継承階層（Provider → CachedProvider → RateLimitedProvider等）→ 複雑さに見合わない
- 設定ファイルによるプロバイダ選択 → コードで十分

## Consequences

- src/providers.py に Protocol定義 + FredAdapter, YFinanceAdapter, NasdaqAdapter を実装
- 既存のsrc/fred_client.pyは変更しない（Adapterでラップ）
- update_data.pyのマクロ取得部分をフォールバックチェーン方式に変更
- 取得した値はParquetにsource列付きで記録。レジーム判定時の入力値はregime_assessmentsスナップショットで保存（ADR-009）
- Tiingo（価格OHLCV）は対象外。マクロ指標のプロバイダのみ抽象化
