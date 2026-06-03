"""延長時間 (プレ/アフター) のリアルタイム現値取得 (ADR-031)。

parquet (CacheManager) はレギュラー時間のみ・最大1日 stale。プレ/アフターに
価格・タイミングが絡む分析をする時、stale 現値を黙って使うと「推測の上に推測」に
なる。本モジュールは on-demand で実勢を取得し、レギュラー終値からの乖離・薄商い
注記を添えた `RealtimeQuote` を返す。**永続化しない** (froth がレギュラー系列を
汚すのを避ける、ADR-001)。

ソース (ADR-031 Decision):
- 主: yfinance prepost (`history(period=1d, interval=1m, prepost=True)` 最終バー)。
  `fast_info.last_price` は使わない (プレマで stale なレギュラー終値を返す実測)。
- 補助裏取り: Tiingo IEX `afterHours=true` (~08:00-16:55 ET の実トレードのみ)。
- Saxo は市場データ未購読 (NoAccess) のため使わない。

価格取得には使わないが、実約定の事実は別途 `account_transactions` (ADR-030) が SoT。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

# tz: JST は src.db と同一定義 (固定オフセット)、ET は DST を扱うため IANA。
JST = timezone(timedelta(hours=9))
ET = ZoneInfo("America/New_York")

# 米国市場の時刻境界 (ET ローカル)。祝日・半日はスコープ外 (ADR-031)。
_PRE_OPEN = time(4, 0)
_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)
_POST_CLOSE = time(20, 0)

# Tiingo IEX afterHours が実トレードを返し始める目安 (ET)。これ以前のプレマは
# yfinance 仲値のみ = froth リスク高 (is_thin 判定に使用)。
_TIINGO_PRE_COVERAGE_START = time(8, 0)


@dataclass(frozen=True)
class ExtendedBar:
    """価格ソースが返す1バーの意味的 snapshot。

    price: バーの終値 (現値プロキシ)。
    bar_time_et: バーの時刻 (ET, aware)。
    volume: 出来高。取れない場合 None (yfinance prepost は None/0 固定)。
    """
    price: float
    bar_time_et: datetime
    volume: Optional[int]


@runtime_checkable
class PriceSource(Protocol):
    """延長時間の最新バーを返すソース (yfinance / Tiingo)。"""

    name: str

    def fetch_latest_extended(self, symbol: str) -> Optional[ExtendedBar]:
        """最新の延長時間バーを返す。取得不能 (時間帯外/データ無) なら None。"""
        ...


@dataclass(frozen=True)
class RealtimeQuote:
    """延長時間の現値 snapshot (ADR-026: raw dict を露出させない意味的アクセサ)。

    Attributes:
        price: 現値 (主ソースの最新バー終値)。
        fetched_at: 取得時刻 (JST, aware)。
        bar_time_et: 現値バーの時刻 (ET)。
        regular_close: 直近レギュラー終値 (parquet)。乖離の基準。
        delta_pct: regular_close からの乖離% (符号付き)。
        session: 'pre' | 'regular' | 'post' | 'closed'。
        source: 現値を返した主ソース名。
        confirm_source / confirm_price: 実トレードで裏取りできた場合のソース/値 (Tiingo)。
            裏取り不能なら None。
        is_thin: 薄商い注記。True の値を sizing/stop の基準アンカーにしない (ADR-031)。
            extended (pre/post/closed) は froth/値持ちしないリスクのため常に True。
    """
    symbol: str
    price: float
    fetched_at: datetime
    bar_time_et: datetime
    regular_close: float
    delta_pct: float
    session: str
    source: str
    confirm_source: Optional[str]
    confirm_price: Optional[float]
    is_thin: bool

    def summary(self) -> str:
        """分析の前段で提示する1行サマリ (現値・乖離・session・取得時刻)。"""
        sign = "+" if self.delta_pct >= 0 else ""
        thin = " ⚠薄商い(froth注意・寄りまで持たない可能性)" if self.is_thin else ""
        conf = (
            f" 裏取り{self.confirm_source}=${self.confirm_price:.2f}"
            if self.confirm_source else " 裏取り無"
        )
        return (
            f"{self.symbol} ${self.price:.2f} ({sign}{self.delta_pct:.2f}% vs 終値${self.regular_close:.2f}) "
            f"[{self.session}] {self.source}{conf} "
            f"@ {self.bar_time_et.strftime('%H:%M ET')} 取得{self.fetched_at.strftime('%H:%M JST')}{thin}"
        )


def classify_session(dt_et: datetime) -> str:
    """ET の aware datetime を 'pre'/'regular'/'post'/'closed' に分類する。

    祝日・半日立会いは未対応 (ADR-031 スコープ外)。週末は closed。
    """
    if dt_et.tzinfo is None:
        raise ValueError("classify_session requires a timezone-aware datetime")
    local = dt_et.astimezone(ET)
    if local.weekday() >= 5:  # 土(5)/日(6)
        return "closed"
    t = local.time()
    if _PRE_OPEN <= t < _REGULAR_OPEN:
        return "pre"
    if _REGULAR_OPEN <= t < _REGULAR_CLOSE:
        return "regular"
    if _REGULAR_CLOSE <= t < _POST_CLOSE:
        return "post"
    return "closed"


def get_realtime_quote(
    symbol: str,
    *,
    regular_close: float,
    primary: PriceSource,
    confirm: Optional[PriceSource] = None,
    now: Optional[datetime] = None,
) -> RealtimeQuote:
    """延長時間の現値を取得し RealtimeQuote を返す (純粋なコア; 注入可能)。

    Args:
        regular_close: 直近レギュラー終値 (乖離の基準)。呼び出し側が CacheManager
            等から渡す。
        primary: 主ソース (yfinance)。最新バーを返せなければ RuntimeError。
        confirm: 裏取りソース (Tiingo)。None / 取得失敗時は confirm_* を None にして継続。
        now: 取得時刻 (JST aware)。省略時は現在時刻。テストは固定値を注入する。

    Raises:
        RuntimeError: 主ソースが現値を返せなかった場合。
    """
    if now is None:
        now = datetime.now(JST)

    bar = primary.fetch_latest_extended(symbol)
    if bar is None:
        raise RuntimeError(
            f"{symbol}: 主ソース {primary.name} が延長時間の現値を返せませんでした "
            "(時間帯外/データ無)。stale parquet を現値扱いしないこと (ADR-031)"
        )

    confirm_source: Optional[str] = None
    confirm_price: Optional[float] = None
    if confirm is not None:
        try:
            cbar = confirm.fetch_latest_extended(symbol)
            if cbar is not None:
                confirm_source = confirm.name
                confirm_price = cbar.price
        except Exception:
            # 裏取り失敗は致命的でない (ADR-031: 主ソースの現値は返す)
            confirm_source = None
            confirm_price = None

    session = classify_session(bar.bar_time_et)
    delta_pct = (bar.price - regular_close) / regular_close * 100.0
    # extended (pre/post/closed) は froth/値持ちしないリスクのため薄商い扱い。
    is_thin = session != "regular"

    return RealtimeQuote(
        symbol=symbol,
        price=bar.price,
        fetched_at=now,
        bar_time_et=bar.bar_time_et,
        regular_close=regular_close,
        delta_pct=delta_pct,
        session=session,
        source=primary.name,
        confirm_source=confirm_source,
        confirm_price=confirm_price,
        is_thin=is_thin,
    )


# ── 実ソース (外部 API; テストでは Fake に差し替える) ─────────────────


class YFinanceExtendedSource:
    """yfinance prepost の最新1分バーを返す (主ソース, ADR-031)。"""

    name = "yfinance"

    def fetch_latest_extended(self, symbol: str) -> Optional[ExtendedBar]:
        import yfinance as yf  # 遅延 import (テスト時に未使用なら不要)

        hist = yf.Ticker(symbol).history(period="1d", interval="1m", prepost=True)
        if hist.empty:
            return None
        last = hist.iloc[-1]
        idx = hist.index[-1]
        bar_time_et = idx.tz_convert(ET).to_pydatetime() if idx.tzinfo else idx.tz_localize("UTC").tz_convert(ET).to_pydatetime()
        v = last.get("Volume")
        vol = int(v) if v and v == v else None  # v==v は NaN を弾く (prepost は 0/NaN)
        return ExtendedBar(price=float(last["Close"]), bar_time_et=bar_time_et, volume=vol)


class TiingoExtendedSource:
    """Tiingo IEX afterHours の最新バーを返す (裏取り, ~08:00-16:55 ET のみ)。"""

    name = "tiingo_iex"

    _DEFAULT_BASE = "https://api.tiingo.com"

    def __init__(self, fetcher=None, base_url: Optional[str] = None):
        # fetcher は requests.Session 互換 (get(url, params, timeout))。None なら遅延構築。
        self._fetcher = fetcher
        self._base = base_url or self._DEFAULT_BASE

    def _session(self):
        if self._fetcher is not None:
            return self._fetcher
        import requests
        from src.tiingo_client import TiingoConfig

        cfg = TiingoConfig.from_env()
        s = requests.Session()
        s.headers.update({"Authorization": f"Token {cfg.api_key}"})
        self._base = cfg.base_url
        return s

    def fetch_latest_extended(self, symbol: str) -> Optional[ExtendedBar]:
        import pandas as pd

        sess = self._session()
        base = self._base
        today_et = datetime.now(ET).date().isoformat()
        params = {
            "resampleFreq": "5min",
            "afterHours": "true",
            "startDate": today_et,
            "format": "json",
        }
        resp = sess.get(f"{base}/iex/{symbol}/prices", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        last = data[-1]
        ts = pd.to_datetime(last["date"]).tz_convert(ET).to_pydatetime()
        vol = int(last["volume"]) if last.get("volume") else None
        return ExtendedBar(price=float(last["close"]), bar_time_et=ts, volume=vol)


def fetch_realtime_quote(symbol: str, *, cache=None, now: Optional[datetime] = None) -> RealtimeQuote:
    """実ソースを配線した便利ラッパー。regular_close は CacheManager から取る。

    分析の前段で呼び、`quote.summary()` を提示してから判断に入る (ADR-031 規律)。
    """
    from pathlib import Path

    if cache is None:
        from src.cache_manager import CacheManager

        cache = CacheManager(Path("data/parquet"))
    daily = cache.load_daily(symbol)
    if daily.empty:
        raise RuntimeError(f"{symbol}: parquet 日足が空。regular_close を決定できない")
    regular_close = float(daily.iloc[-1]["Close"])

    return get_realtime_quote(
        symbol,
        regular_close=regular_close,
        primary=YFinanceExtendedSource(),
        confirm=TiingoExtendedSource(),
        now=now,
    )
