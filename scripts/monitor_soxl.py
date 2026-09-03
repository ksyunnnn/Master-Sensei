"""SOXL（および任意のレバ ETF）ライブ監視ツール。

セッションごとに使い捨てしていた monitor スクリプト群を汎用化したもの。
当日値（前日終値・zone・終了時刻）は CLI 引数で渡し、signal 判定ロジック
（classify）は恒久資産として固定する。

監視内容:
  - SOX 連動性の乖離: primary pct ≈ reference pct × leverage からの逸脱を検知
  - driver retrace: 当日 driver（例 MU）の高値からの戻り = SOX 弱体の先行警報
  - reversal: session 高安からの ±N% 反転 + lead driver（例 NVDA）の leadership 確認
  - zone fill: long dip / short rally の指値水準への接近（発注済 limit の約定圏通知）
  - intraday volatility flag / deep dip / gap fill

価格は yfinance（prepost=True、延長時間含む）から取得。新規 trigger 発生時のみ
terminal-notifier で通知し、同一 trigger の連続通知は dedup する。

使い方の例:
    # 5/28 セッション相当（前日終値を明示、long dip 3段 / short rally 2段）
    python scripts/monitor_soxl.py \\
        --prior-close SOXL=217.98 \\
        --long-dip 210,205,200 --short-rally 230,235 \\
        --poll-sec 60 --until 05:00

    # 1 回だけ現在値スナップショットを表示して終了
    python scripts/monitor_soxl.py --prior-close SOXL=217.98 --once
"""
import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import yfinance as yf  # noqa: E402

JST = timezone(timedelta(hours=9))


# ── 設定 ──────────────────────────────────────────────

@dataclass
class MonitorConfig:
    """signal 判定の閾値・zone。CLI 引数から構築する。"""
    symbol: str
    reference: str
    leverage: float
    long_dip: list[float]
    short_rally: list[float]
    fill_tolerance: float
    reversal_pct: float
    vol_flag_pct: float
    sox_divergence: float
    driver_retrace_pct: float
    lead_flip_pct: float
    ref_rebound_pct: float
    # REVERSAL UP を認める lead driver の下限 %。既定 0.0 は「lead が
    # プラス転換するまで底打ちを認めない」。セクター全面安の日は lead が
    # プラスに戻る前にレバ ETF が底打ちするため、その日は負値まで緩める。
    reversal_lead_min: float = 0.0
    lead_driver: str = "NVDA"
    retrace_driver: str = "MU"
    drivers: list[str] = field(default_factory=lambda: ["MU", "NVDA", "AMD"])


# ── 純粋ロジック（テスト対象） ────────────────────────────

def pct_from(price: float | None, base: float | None) -> float | None:
    """base 比の変化率（%）。price/base が None かゼロなら None。"""
    if price is None or base is None or base == 0:
        return None
    return (price / base - 1) * 100


def classify(
    *,
    price: float,
    pct: float | None,
    ref_pct: float | None,
    lead_pct: float | None,
    retrace_driver_pct: float | None,
    retrace_driver_high_pct: float | None,
    session_high: float,
    session_low: float,
    cfg: MonitorConfig,
) -> tuple[str, str | None]:
    """現在のスナップショットを state ラベル + trigger code に分類する。

    trigger code は notify の dedup key。None なら通知不要（通常観測）。
    優先順位は「反転 > zone 接近 > ボラ > 連動乖離 > driver 弱体 > 極端領域」。
    """
    # 1. reversal up: session 安値からの bounce + lead driver の leadership 維持
    if session_low > 0:
        bounce_pct = (price - session_low) / session_low * 100
        if (bounce_pct >= cfg.reversal_pct and lead_pct is not None
                and lead_pct >= cfg.reversal_lead_min):
            return (
                f"REVERSAL UP: session low ${session_low:.2f} → ${price:.2f} "
                f"(+{bounce_pct:.1f}%)、{cfg.lead_driver} {lead_pct:+.2f}% "
                f"(下限 {cfg.reversal_lead_min:+.1f}%)",
                f"REVERSAL_UP_FROM_{int(session_low)}",
            )

    # 2. reversal down: session 高値からの drop + lead driver の leadership 崩壊
    if session_high > 0 and price < session_high:
        drop_pct = (session_high - price) / session_high * 100
        if drop_pct >= cfg.reversal_pct and lead_pct is not None and lead_pct <= -0.5:
            return (
                f"REVERSAL DOWN: session high ${session_high:.2f} → ${price:.2f} "
                f"(-{drop_pct:.1f}%)、{cfg.lead_driver} {lead_pct:+.2f}% leadership 崩壊",
                f"REVERSAL_DOWN_FROM_{int(session_high)}",
            )

    # 3. long dip / short rally zone の約定圏
    for zone in cfg.long_dip:
        if abs(price - zone) <= cfg.fill_tolerance:
            return (f"long dip ${zone:.0f} 約定圏 (${price:.2f})", f"LONG_DIP_{int(zone)}")
    for zone in cfg.short_rally:
        if abs(price - zone) <= cfg.fill_tolerance:
            return (f"short rally ${zone:.0f} 約定圏 (${price:.2f})", f"SHORT_RALLY_{int(zone)}")

    # 4. intraday volatility flag
    if session_low > 0:
        intraday_range_pct = (session_high - session_low) / session_low * 100
        if intraday_range_pct >= cfg.vol_flag_pct:
            return (
                f"intraday volatility flag: range ${session_low:.2f}-${session_high:.2f} "
                f"({intraday_range_pct:.1f}%)",
                f"VOL_FLAG_{int(intraday_range_pct)}",
            )

    # 5. SOX 連動乖離（primary pct vs reference pct × leverage）
    if ref_pct is not None and pct is not None:
        expected = ref_pct * cfg.leverage
        spread = pct - expected
        if spread < -cfg.sox_divergence:
            return (
                f"{cfg.symbol} underperform (SOX 想定より {spread:+.1f}%、bounce 機会)",
                "SOXL_UNDER",
            )
        if spread > cfg.sox_divergence:
            return (
                f"{cfg.symbol} outperform (SOX 想定より {spread:+.1f}%、leverage decay リスク)",
                "SOXL_OVER",
            )

    # 6. driver retrace（当日 driver の高値からの戻り = SOX driver 弱体の先行警報）
    if retrace_driver_high_pct is not None and retrace_driver_pct is not None:
        retracement = retrace_driver_high_pct - retrace_driver_pct
        if retracement > cfg.driver_retrace_pct:
            return (
                f"{cfg.retrace_driver} reversal (高値 +{retrace_driver_high_pct:.1f}% から "
                f"{retracement:.1f}% 戻り = SOX driver 弱体)",
                "MU_REVERSAL",
            )

    # 7. lead driver flip / reference rebound
    if lead_pct is not None and lead_pct < cfg.lead_flip_pct:
        return (
            f"{cfg.lead_driver} leadership flip ({cfg.lead_driver} {lead_pct:+.2f}%)",
            "NVDA_FLIP",
        )
    if ref_pct is not None and ref_pct > cfg.ref_rebound_pct:
        return (
            f"SOX rebound ({cfg.reference} {ref_pct:+.2f}%、chip selloff reversal 候補)",
            "SOX_REBOUND",
        )

    # 8. 極端領域（zone レンジの外側）
    if cfg.long_dip and price < min(cfg.long_dip) - cfg.fill_tolerance:
        return (f"{cfg.symbol} deep dip <${min(cfg.long_dip):.0f} (最安 zone 割れ)", "DEEP_DIP")
    if cfg.short_rally and price > max(cfg.short_rally) + cfg.fill_tolerance:
        return (f"{cfg.symbol} gap-fill rally >${max(cfg.short_rally):.0f} (最高 zone 超え)", "GAP_FILL")

    return (f"normal observation (range {session_low:.1f}-{session_high:.1f})", None)


def should_notify(action: str | None, fired: set[str]) -> bool:
    """この trigger code を通知すべきか。既に通知済みの code は抑止する。

    zone 判定は `abs(price - zone) <= fill_tolerance` の帯なので、価格が帯の
    境界に留まると「帯の中→外→中」を往復する。直前の action と比較するだけの
    dedup では帯を出るたびに状態がリセットされ、同じ code が繰り返し通知される。
    セッション内で発火済みの code を集合で保持し、一度きりに固定する。

    水準が変われば code 自体が変わる設計（REVERSAL_UP_FROM_100 と
    REVERSAL_UP_FROM_98 は別 code、VOL_FLAG_N は range を埋め込む）なので、
    code 単位の抑止で新しい水準の到達は取りこぼさない。
    """
    return action is not None and action not in fired


# ── I/O（テスト対象外） ──────────────────────────────────

def fetch_prior_close(symbols: tuple[str, ...], date_str: str | None,
                      overrides: dict[str, float]) -> dict[str, float]:
    """直近の確定 daily close を取得。

    date_str 指定時はその日付の終値を date column で明示 filter（市場時間中は
    iloc[-1] が today の未確定 bar になるため）。未指定時は最後から 2 本目
    （= 直近の確定足）を使う。overrides は最後に上書き（yfinance が不安定な
    銘柄を手動補正するため）。
    """
    import pandas as pd
    target = pd.Timestamp(date_str).date() if date_str else None
    out: dict[str, float] = {}
    for sym in symbols:
        try:
            hist = yf.Ticker(sym).history(period="7d", interval="1d", prepost=False)
            if hist.empty:
                continue
            if target is not None:
                matches = hist[hist.index.date == target]
                if not matches.empty:
                    out[sym] = float(matches["Close"].iloc[0])
                    continue
            # date 未指定 or 該当なし → 直近の確定足（今日の未確定足を避ける）
            out[sym] = float(hist["Close"].iloc[-2] if len(hist) >= 2 else hist["Close"].iloc[-1])
        except Exception:
            pass
    out.update(overrides)
    return out


def fetch_realtime(symbols: tuple[str, ...]) -> dict[str, float]:
    """直近 1 分足の close（prepost=True で延長時間も拾う）。"""
    out: dict[str, float] = {}
    for sym in symbols:
        try:
            hist = yf.Ticker(sym).history(period="1d", interval="1m", prepost=True)
            if not hist.empty:
                out[sym] = float(hist["Close"].iloc[-1])
        except Exception:
            pass
    return out


def notify(title: str, msg: str) -> None:
    try:
        subprocess.run(
            ["terminal-notifier", "-title", title, "-subtitle", "SOXL Monitor",
             "-message", msg, "-sound", "Glass"],
            check=False, capture_output=True,
        )
    except FileNotFoundError:
        pass


def _parse_prices(spec: str | None) -> list[float]:
    if not spec:
        return []
    return [float(x) for x in spec.split(",") if x.strip()]


def _parse_overrides(spec: str | None) -> dict[str, float]:
    """'SOXL=217.98,SOXX=559.91' → {'SOXL': 217.98, 'SOXX': 559.91}"""
    out: dict[str, float] = {}
    if not spec:
        return out
    for pair in spec.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip().upper()] = float(v)
    return out


def _resolve_end(until: str) -> datetime:
    hh, mm = (int(x) for x in until.split(":"))
    now = datetime.now(JST)
    end = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if end <= now:
        end += timedelta(days=1)
    return end


def run(cfg: MonitorConfig, prior_close: dict[str, float], symbols: tuple[str, ...],
        poll_sec: int, end_at: datetime, once: bool) -> None:
    now = datetime.now(JST)
    have = " ".join(f"{s}=${prior_close[s]:.2f}" for s in symbols if prior_close.get(s))
    print(f"[INIT {now:%H:%M:%S}] prior closes: {have}", flush=True)
    for sym in symbols:
        if prior_close.get(sym) is None:
            print(f"[INIT] WARN: {sym} prior close 取得不可（--prior-close で補正可）", flush=True)
    print(f"[START {now:%H:%M:%S}] {'snapshot once' if once else f'until {end_at:%m/%d %H:%M} JST'}, "
          f"poll {poll_sec}s | long dip {cfg.long_dip} short rally {cfg.short_rally}", flush=True)

    fired: set[str] = set()
    retrace_high_pct: float | None = None
    session_high = -1.0
    session_low = 1e9

    while True:
        now = datetime.now(JST)
        if not once and now >= end_at:
            print(f"[END {now:%H:%M:%S}] scheduled stop", flush=True)
            notify("Master Sensei", f"{cfg.symbol} monitor stopped ({end_at:%H:%M} JST)")
            break

        prices = fetch_realtime(symbols)
        price = prices.get(cfg.symbol)
        if price is None:
            print(f"[{now:%H:%M:%S}] {cfg.symbol} fetch error, retry", flush=True)
            if once:
                break
            time.sleep(poll_sec)
            continue

        pct = pct_from(price, prior_close.get(cfg.symbol))
        ref_pct = pct_from(prices.get(cfg.reference), prior_close.get(cfg.reference))
        lead_pct = pct_from(prices.get(cfg.lead_driver), prior_close.get(cfg.lead_driver))
        retrace_pct = pct_from(prices.get(cfg.retrace_driver), prior_close.get(cfg.retrace_driver))

        if retrace_pct is not None and (retrace_high_pct is None or retrace_pct > retrace_high_pct):
            retrace_high_pct = retrace_pct
        session_high = max(session_high, price)
        session_low = min(session_low, price)

        state, action = classify(
            price=price, pct=pct, ref_pct=ref_pct, lead_pct=lead_pct,
            retrace_driver_pct=retrace_pct, retrace_driver_high_pct=retrace_high_pct,
            session_high=session_high, session_low=session_low, cfg=cfg,
        )

        head = f"{cfg.symbol}=${price:.2f}" + (f"({pct:+.2f}%)" if pct is not None else "")
        parts = [head]
        for sym in (cfg.reference, *cfg.drivers):
            p = pct_from(prices.get(sym), prior_close.get(sym))
            if p is not None:
                parts.append(f"{sym}({p:+.2f}%)")
        line = f"[{now:%H:%M:%S}] " + " ".join(parts) + f" | {state}"

        if should_notify(action, fired):
            print(f"!!! TRIGGER [{action}] {line}", flush=True)
            notify("Master Sensei", f"{action}: {cfg.symbol} ${price:.2f} | {state}")
            fired.add(action)
        else:
            print(line, flush=True)

        if once:
            break
        time.sleep(poll_sec)


def main() -> None:
    ap = argparse.ArgumentParser(description="SOXL ライブ監視（汎用版）")
    ap.add_argument("--symbol", default="SOXL", help="監視対象のレバ ETF")
    ap.add_argument("--reference", default="SOXX", help="1x ベンチマーク（連動乖離の基準）")
    ap.add_argument("--leverage", type=float, default=3.0, help="symbol/reference のレバ倍率")
    ap.add_argument("--lead-driver", default="NVDA", help="reversal の leadership 確認に使う driver")
    ap.add_argument("--retrace-driver", default="MU", help="高値 retrace 早期警報に使う driver")
    ap.add_argument("--drivers", default="MU,NVDA,AMD", help="併走表示する driver（カンマ区切り）")
    ap.add_argument("--prior-close-date", default=None, help="前日終値の対象日 YYYY-MM-DD（未指定で自動）")
    ap.add_argument("--prior-close", default=None, help="前日終値の手動補正 'SOXL=217.98,SOXX=559.91'")
    ap.add_argument("--long-dip", default="210,205,200", help="long dip zone（カンマ区切り）")
    ap.add_argument("--short-rally", default="230,235", help="short rally zone（カンマ区切り）")
    ap.add_argument("--fill-tolerance", type=float, default=1.5, help="zone 約定圏の許容幅 ±$")
    ap.add_argument("--reversal-pct", type=float, default=1.5, help="session 高安からの反転閾値 ％")
    ap.add_argument("--vol-flag-pct", type=float, default=3.0, help="intraday range のボラフラグ閾値 ％")
    ap.add_argument("--sox-divergence", type=float, default=2.0, help="連動乖離の閾値 ％")
    ap.add_argument("--driver-retrace-pct", type=float, default=3.0, help="driver 高値 retrace 警報閾値 ％")
    ap.add_argument("--lead-flip-pct", type=float, default=-1.5, help="lead driver flip 閾値 ％")
    ap.add_argument("--ref-rebound-pct", type=float, default=1.5, help="reference rebound 閾値 ％")
    ap.add_argument("--reversal-lead-min", type=float, default=0.0,
                    help="REVERSAL UP を認める lead driver の下限 ％（既定 0.0＝プラス転換必須）")
    ap.add_argument("--poll-sec", type=int, default=60, help="polling 間隔（秒）")
    ap.add_argument("--until", default="05:00", help="終了時刻 HH:MM JST（過ぎていれば翌日）")
    ap.add_argument("--once", action="store_true", help="1 回スナップショットを出して終了")
    args = ap.parse_args()

    drivers = [s.strip().upper() for s in args.drivers.split(",") if s.strip()]
    cfg = MonitorConfig(
        symbol=args.symbol.upper(),
        reference=args.reference.upper(),
        leverage=args.leverage,
        long_dip=_parse_prices(args.long_dip),
        short_rally=_parse_prices(args.short_rally),
        fill_tolerance=args.fill_tolerance,
        reversal_pct=args.reversal_pct,
        vol_flag_pct=args.vol_flag_pct,
        sox_divergence=args.sox_divergence,
        driver_retrace_pct=args.driver_retrace_pct,
        lead_flip_pct=args.lead_flip_pct,
        ref_rebound_pct=args.ref_rebound_pct,
        reversal_lead_min=args.reversal_lead_min,
        lead_driver=args.lead_driver.upper(),
        retrace_driver=args.retrace_driver.upper(),
        drivers=drivers,
    )

    symbols = tuple(dict.fromkeys([cfg.symbol, cfg.reference, cfg.lead_driver,
                                   cfg.retrace_driver, *cfg.drivers]))
    prior_close = fetch_prior_close(symbols, args.prior_close_date,
                                    _parse_overrides(args.prior_close))
    run(cfg, prior_close, symbols, args.poll_sec, _resolve_end(args.until), args.once)


if __name__ == "__main__":
    main()
