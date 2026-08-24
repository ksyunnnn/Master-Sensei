"""マクロデータプロバイダ抽象化（ADR-006）

Protocol + Adapterパターンでプロバイダを統一。
フォールバックチェーンで可用性を確保する。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── シリーズ名マッピング ──
# 統一シリーズ名 → プロバイダ固有ティッカー

FRED_SERIES = {
    "VIX": "VIXCLS",
    "VIX3M": "VXVCLS",
    "VXN": "VXNCLS",
    "BRENT": "DCOILBRENTEU",
    "US10Y": "DGS10",
    "US30Y": "DGS30",
    # 金利の分解(2026-08-24 実測、issue#26)。名目金利は「実質金利 + 期待インフレ」で、
    # この2つは SOXX に逆符号で効くため、名目単独では打ち消し合って情報が消える
    # (5年 n=1289 の重回帰: 実質 -0.573%/10bp t=-3.30、期待インフレ +0.928%/10bp
    # t=+3.18、両者の日次変化の相関 -0.022。名目単独は r=-0.035 t=-1.24 で有意でない)。
    # 帰属(下げた原因の切り分け)に使う。予測には使えない -> K-074。
    "REAL10Y": "DFII10",
    "REAL30Y": "DFII30",
    "BREAKEVEN10Y": "T10YIE",
    "FEDFUNDS": "FEDFUNDS",
    "YIELD_CURVE": "T10Y2Y",
    "HY_SPREAD": "BAMLH0A0HYM2",
    "USD_INDEX": "DTWEXBGS",
}

YFINANCE_SERIES = {
    "VIX": "^VIX",
    "VIX3M": "^VIX3M",
    "BRENT": "BZ=F",
    # MOVE = 債券市場のボラティリティ指数(株の VIX に相当)。FRED に無いため yfinance から取る。
    # 2026-08-24 実測で、金利テーマの全変数のうち唯一、半導体固有の下げ(SOXX - SPY)に
    # 5年通して有意だった(SOXX r=-0.184 t=-6.72、超過 t=-3.31)。
    # ただし K-073 の基準では未検証: 一次公表元は ICE BofA で無償の照合先が無く、
    # ^TYX で起きたようなズレが無いことを確認できていない。使う時はこの制約込みで扱う。
    "MOVE": "^MOVE",
}

# US30Y を yfinance(^TYX) から取らない理由(issue#26、2026-08-24 実測):
# 米財務省が公表する日次利回り曲線(30 Yr)を基準に 2026年の159営業日を突合したところ、
# FRED DGS30 は 159/159 日で完全一致(差 0.0000)、対して ^TYX は完全一致ゼロ、
# 財務省と同じ小数第2位に丸めても一致は 89/159 日(56%)、最大差 0.0570(2026-07-29:
# 財務省 5.20 / ^TYX 5.143)だった。この 0.06 は週次の金利変動(直近3週で +0.054/+0.011)と
# 同オーダーで、閾値判定に使うには無視できない。
# 2ソースを互いに突合すると相関 0.999945 で「一致」に見えるが、一致は正確さの証明ではない。
# 代償として FRED は日次確定値で 1-2日遅延する。日中値が要るなら別途 ProviderChain を
# 組むのでなく、財務省の日次公表を直接引く経路を検討する。

NASDAQ_SERIES = {
    "VIX": "CBOE/VIX",
}


# ── Protocol定義 ──

@runtime_checkable
class MacroProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    def fetch_series(
        self, series: str, start_date: date, end_date: date
    ) -> list[dict]:
        """Returns [{"date": "YYYY-MM-DD", "value": float}, ...]"""
        ...

    def available_series(self) -> list[str]: ...


# ── Adapters ──

class FredAdapter:
    """FRED APIをMacroProviderインターフェースに適合させるAdapter"""

    def __init__(self, fred_client):
        self._client = fred_client
        self._series_map = FRED_SERIES

    @property
    def provider_name(self) -> str:
        return "fred"

    def available_series(self) -> list[str]:
        return list(self._series_map.keys())

    def fetch_series(
        self, series: str, start_date: date, end_date: date
    ) -> list[dict]:
        fred_id = self._series_map.get(series)
        if not fred_id:
            raise ValueError(f"Series '{series}' not available in FRED")
        return self._client.fetch_series(fred_id, start_date=start_date, end_date=end_date)


class YFinanceAdapter:
    """yfinanceをMacroProviderインターフェースに適合させるAdapter"""

    def __init__(self):
        self._series_map = YFINANCE_SERIES

    @property
    def provider_name(self) -> str:
        return "yfinance"

    def available_series(self) -> list[str]:
        return list(self._series_map.keys())

    def fetch_series(
        self, series: str, start_date: date, end_date: date
    ) -> list[dict]:
        import yfinance as yf

        ticker_symbol = self._series_map.get(series)
        if not ticker_symbol:
            raise ValueError(f"Series '{series}' not available in yfinance")

        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(start=start_date.isoformat(), end=(end_date + __import__('datetime').timedelta(days=1)).isoformat())

        if hist.empty:
            return []

        records = []
        for idx, row in hist.iterrows():
            records.append({
                "date": idx.strftime("%Y-%m-%d"),
                "value": float(row["Close"]),
            })
        return records


class NasdaqAdapter:
    """Nasdaq Data Link (旧Quandl)をMacroProviderインターフェースに適合させるAdapter

    注意: CBOE/VIXは有料化済みの可能性あり。利用可能性の検証用に実装。
    """

    def __init__(self, api_key: str):
        import nasdaqdatalink
        nasdaqdatalink.ApiConfig.api_key = api_key
        self._series_map = NASDAQ_SERIES

    @property
    def provider_name(self) -> str:
        return "nasdaq"

    def available_series(self) -> list[str]:
        return list(self._series_map.keys())

    def fetch_series(
        self, series: str, start_date: date, end_date: date
    ) -> list[dict]:
        import nasdaqdatalink

        nasdaq_code = self._series_map.get(series)
        if not nasdaq_code:
            raise ValueError(f"Series '{series}' not available in Nasdaq Data Link")

        df = nasdaqdatalink.get(
            nasdaq_code,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )

        if df.empty:
            return []

        # CBOE/VIXの場合、Close列を使う
        value_col = "Close" if "Close" in df.columns else df.columns[0]
        records = []
        for idx, row in df.iterrows():
            records.append({
                "date": idx.strftime("%Y-%m-%d"),
                "value": float(row[value_col]),
            })
        return records


# ── フォールバックチェーン ──

class ProviderChain:
    """複数プロバイダをフォールバック順に試行する

    Usage:
        chain = ProviderChain([yfinance_adapter, nasdaq_adapter, fred_adapter])
        records = chain.fetch("VIX", start, end)
        # → yfinance成功ならyfinanceの値、失敗ならnasdaq、それも失敗ならfred
    """

    def __init__(self, providers: list[MacroProvider]):
        self.providers = providers

    def fetch(
        self, series: str, start_date: date, end_date: date
    ) -> tuple[list[dict], str]:
        """Returns (records, provider_name) or raises if all fail"""
        errors = []
        for provider in self.providers:
            if series not in provider.available_series():
                continue
            try:
                records = provider.fetch_series(series, start_date, end_date)
                if records:
                    logger.info(f"{series}: fetched from {provider.provider_name} ({len(records)} records)")
                    return records, provider.provider_name
                else:
                    logger.debug(f"{series}: {provider.provider_name} returned empty")
            except Exception as e:
                logger.warning(f"{series}: {provider.provider_name} failed: {e}")
                errors.append((provider.provider_name, str(e)))

        error_msg = "; ".join(f"{name}: {err}" for name, err in errors)
        raise RuntimeError(f"All providers failed for '{series}': {error_msg}")

    def available_series(self) -> set[str]:
        result = set()
        for provider in self.providers:
            result.update(provider.available_series())
        return result
