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
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from src.market_calendar import (
    is_trading_day,
    previous_trading_day,
    trading_days_between,
)

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
        regular_close_date: regular_close がどの日の終値かを名指しする日付。
            現値だけ realtime に差し替えても基準が stale なら乖離%は無意味になるため、
            基準の出所を値と一緒に持ち歩く。
        baseline_stale_days: 期待される基準日から何営業日ぶん古いか (0 なら最新)。
        delta_pct: regular_close からの乖離% (符号付き)。基準が stale (>0営業日) の時は
            None。古い基準との乖離%は方向を逆に読ませるため、値を出さない (ADR-031)。
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
    regular_close_date: date
    baseline_stale_days: int
    delta_pct: Optional[float]
    session: str
    source: str
    confirm_source: Optional[str]
    confirm_price: Optional[float]
    is_thin: bool

    @property
    def is_baseline_stale(self) -> bool:
        """乖離の基準が期待より古いか。True なら delta_pct は None。"""
        return self.baseline_stale_days > 0

    def summary(self) -> str:
        """分析の前段で提示する1行サマリ (現値・乖離・session・取得時刻)。

        基準日は stale の有無にかかわらず常に出す。読み手が「いつの終値と
        比べた数字か」を検算できない状態を作らないため。
        """
        thin = " ⚠薄商い(froth注意・寄りまで持たない可能性)" if self.is_thin else ""
        conf = (
            f" 裏取り{self.confirm_source}=${self.confirm_price:.2f}"
            if self.confirm_source else " 裏取り無"
        )
        base_date = self.regular_close_date.strftime("%m-%d")
        if self.delta_pct is None:
            cmp_part = (
                f"⚠乖離%なし: 基準の{base_date}終値${self.regular_close:.2f} が"
                f"{self.baseline_stale_days}営業日古い→update_data.py"
            )
        else:
            sign = "+" if self.delta_pct >= 0 else ""
            cmp_part = f"{sign}{self.delta_pct:.2f}% vs {base_date}終値${self.regular_close:.2f}"
        return (
            f"{self.symbol} ${self.price:.2f} ({cmp_part}) "
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


def latest_regular_close_date(dt_et: datetime) -> date:
    """dt_et の時点で確定している直近レギュラー終値の日付を返す。

    乖離%の基準として「本来どの日の終値を使うべきか」を決める。引け (16:00 ET)
    より前は当日の終値がまだ無いので前営業日まで戻る。週末・祝日は
    `src.market_calendar` で飛ばす。

    祝日を飛ばさないと、祝日の翌営業日に「データが1日古い」と誤検知する。その警告は
    データを更新しても消えない (存在しない日の終値を待つことになる) ため、警告を無視
    する習慣を作ってしまう。半日立会いは終値が存在するので営業日として扱う。
    """
    if dt_et.tzinfo is None:
        raise ValueError("latest_regular_close_date requires a timezone-aware datetime")
    local = dt_et.astimezone(ET)
    day = local.date()
    if local.time() >= _REGULAR_CLOSE and is_trading_day(day):
        return day
    return previous_trading_day(day)


def get_realtime_quote(
    symbol: str,
    *,
    regular_close: float,
    regular_close_date: date,
    primary: PriceSource,
    confirm: Optional[PriceSource] = None,
    now: Optional[datetime] = None,
) -> RealtimeQuote:
    """延長時間の現値を取得し RealtimeQuote を返す (純粋なコア; 注入可能)。

    Args:
        regular_close: 直近レギュラー終値 (乖離の基準)。呼び出し側が CacheManager
            等から渡す。
        regular_close_date: regular_close がどの日の終値か。**必須**。省略可能に
            すると呼び出し側が基準の鮮度を黙って落とせてしまい、stale な終値との
            乖離%を「現値の動き」と誤読する事故が再発する (ADR-031)。
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

    # 乖離%は「現値」と「基準終値」の関係なので、片方が stale なら結果も無意味。
    # 基準が古い時は計算せず None にして、誤読の源そのものを消す (ADR-031)。
    expected_baseline = latest_regular_close_date(bar.bar_time_et)
    baseline_stale_days = trading_days_between(regular_close_date, expected_baseline)
    delta_pct: Optional[float] = None
    if baseline_stale_days == 0:
        delta_pct = (bar.price - regular_close) / regular_close * 100.0

    # extended (pre/post/closed) は froth/値持ちしないリスクのため薄商い扱い。
    is_thin = session != "regular"

    return RealtimeQuote(
        symbol=symbol,
        price=bar.price,
        fetched_at=now,
        bar_time_et=bar.bar_time_et,
        regular_close=regular_close,
        regular_close_date=regular_close_date,
        baseline_stale_days=baseline_stale_days,
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


def _baseline_date_from_daily(daily) -> date:
    """parquet 日足の最終行が「いつの終値か」を取り出す。

    CacheManager.load_daily は Date を DatetimeIndex に持つ。日付が取れない形の
    DataFrame は、鮮度を検査できないまま乖離%を出すことになるので黙って続けず
    RuntimeError にする (ADR-031: stale を黙って使わせない)。
    """
    idx = daily.index[-1]
    if isinstance(idx, date) and not isinstance(idx, datetime):
        return idx
    if hasattr(idx, "date"):
        return idx.date()
    if "Date" in daily.columns:
        col = daily.iloc[-1]["Date"]
        return col if isinstance(col, date) and not isinstance(col, datetime) else col.date()
    raise RuntimeError(
        "parquet 日足から基準日を決定できない (Date が index にも列にも無い)。"
        "基準の鮮度を検査せずに乖離%を出さない (ADR-031)"
    )


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
    last = daily.iloc[-1]
    regular_close = float(last["Close"])
    # 終値の「日付」も一緒に運ぶ。値だけ渡すと parquet が何日 stale でも
    # 乖離%が計算されてしまい、古い終値との差を現値の動きと誤読する (ADR-031)。
    regular_close_date = _baseline_date_from_daily(daily)

    return get_realtime_quote(
        symbol,
        regular_close=regular_close,
        regular_close_date=regular_close_date,
        primary=YFinanceExtendedSource(),
        confirm=TiingoExtendedSource(),
        now=now,
    )
