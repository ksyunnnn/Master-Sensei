"""Round 2 探索仮説（exploratory）

Round 1結果分析から生成した新仮説。
全てexploratoryラベル付き。有望なものは次のRound 1確認に回す。

アプローチ:
  6. DuckDB eventsベースシグナル
  5. データ駆動（リターンパターンの逆引き）
  4. クロスアセットリード/ラグ
  3. 時間帯特化パターン
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# ── アプローチ6: イベントベースシグナル ──

SENSEI_DB = Path(__file__).resolve().parent.parent / ".." / "master_sensei" / "data" / "sensei.duckdb"


def _load_events() -> pd.DataFrame:
    """DuckDBからイベントを読み込む。"""
    if not SENSEI_DB.exists():
        return pd.DataFrame()
    con = duckdb.connect(str(SENSEI_DB), read_only=True)
    df = con.execute(
        "SELECT event_timestamp, category, impact FROM events ORDER BY event_timestamp"
    ).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["event_timestamp"]).dt.date
    return df


_EVENTS_CACHE: pd.DataFrame | None = None


def _get_events() -> pd.DataFrame:
    global _EVENTS_CACHE
    if _EVENTS_CACHE is None:
        _EVENTS_CACHE = _load_events()
    return _EVENTS_CACHE


def _event_count_by_date(category: str | None = None, impact: str | None = None) -> dict:
    """日付ごとのイベント件数を辞書で返す。"""
    ev = _get_events()
    if category:
        ev = ev[ev["category"] == category]
    if impact:
        ev = ev[ev["impact"] == impact]
    return ev.groupby("date").size().to_dict()


def h_r2_event_density_7d(df):
    """過去7日間のイベント密度（件数）。高密度=ボラティリティ予測。"""
    counts = _event_count_by_date()
    dates = [ts.date() if hasattr(ts, "date") else ts for ts in df.index]
    result = []
    for d in dates:
        total = sum(counts.get(d - pd.Timedelta(days=i), 0) for i in range(7)
                    if isinstance(d, object))
        result.append(total)
    return pd.Series(result, index=df.index, dtype=float)


def h_r2_neg_event_cluster(df):
    """過去5日間のnegativeイベント件数。高→逆張りロング候補。"""
    counts = _event_count_by_date(impact="negative")
    dates = [ts.date() if hasattr(ts, "date") else ts for ts in df.index]
    import datetime
    result = []
    for d in dates:
        total = 0
        for i in range(5):
            try:
                key = d - datetime.timedelta(days=i)
                total += counts.get(key, 0)
            except TypeError:
                pass
        result.append(total)
    return pd.Series(result, index=df.index, dtype=float)


def h_r2_geo_event_flag(df):
    """過去3日間に地政学イベントがあったか。bool。"""
    counts = _event_count_by_date(category="geopolitical")
    dates = [ts.date() if hasattr(ts, "date") else ts for ts in df.index]
    import datetime
    result = []
    for d in dates:
        any_event = False
        for i in range(3):
            try:
                key = d - datetime.timedelta(days=i)
                if counts.get(key, 0) > 0:
                    any_event = True
                    break
            except TypeError:
                pass
        result.append(any_event)
    return pd.Series(result, index=df.index, dtype=bool)


# ── アプローチ5: データ駆動 ──


def h_r2_extreme_down_reversal(df):
    """前日リターンが-3%以下（極端下落）→ 翌日反発候補。bool。"""
    ret = df["Close"].pct_change()
    return ret.shift(1) < -0.03


def h_r2_vol_compression_breakout(df):
    """5日間の実現ボラティリティが20日間の半分以下 → ブレイクアウト前兆。bool。"""
    ret = df["Close"].pct_change()
    rv5 = ret.rolling(5).std()
    rv20 = ret.rolling(20).std()
    return rv5 < rv20 * 0.5


def h_r2_gap_fill_tendency(df):
    """ギャップアップ後に前日終値に戻る傾向。ギャップ率を返す（float）。"""
    prev_close = df["Close"].shift(1)
    gap = (df["Open"] - prev_close) / prev_close * 100
    return gap.where(gap.abs() > 0.5, np.nan)


def h_r2_friday_effect(df):
    """金曜日フラグ。曜日効果の検証。bool。"""
    return pd.Series(df.index.dayofweek == 4, index=df.index, dtype=bool)


def h_r2_month_start(df):
    """月初5営業日フラグ。月初フロー効果。bool。"""
    dom = df.index.day
    return dom <= 7


# ── アプローチ4: クロスアセットリード ──


def h_r2_spy_lead(df):
    """SPYの前日リターン。クロスアセットリード（要pair_Close=SPY）。"""
    if "pair_Close" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df["pair_Close"].pct_change().shift(1) * 100


def h_r2_qqq_lead(df):
    """QQQの前日リターン。クロスアセットリード（要pair_Close=QQQ）。"""
    if "pair_Close" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df["pair_Close"].pct_change().shift(1) * 100


def h_r2_hyg_lead(df):
    """HYGの前日リターン。クレジットリスクのリード（要pair_Close=HYG）。"""
    if "pair_Close" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df["pair_Close"].pct_change().shift(1) * 100


def h_r2_tlt_inverse_lead(df):
    """TLTの前日リターンの逆。金利上昇→リスクオフ（要pair_Close=TLT）。"""
    if "pair_Close" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return -df["pair_Close"].pct_change().shift(1) * 100


# ── アプローチ3: 時間帯特化（5分足用）──


def h_r2_opening_30min_momentum(df):
    """開場30分(09:30-10:00)のリターン。5分足用。"""
    import datetime
    t = df.index.time
    is_open_30 = (t >= datetime.time(9, 30)) & (t < datetime.time(10, 0))
    dates = pd.Series([ts.date() for ts in df.index], index=df.index)
    open_ret = df["Close"].pct_change().where(is_open_30, np.nan)
    daily_open_ret = open_ret.groupby(dates).sum()
    return dates.map(daily_open_ret).astype(float)


def h_r2_last_30min_momentum(df):
    """引け前30分(15:30-16:00)のリターン。前日分。5分足用。"""
    import datetime
    t = df.index.time
    is_close_30 = (t >= datetime.time(15, 25)) & (t <= datetime.time(15, 55))
    dates = pd.Series([ts.date() for ts in df.index], index=df.index)
    close_ret = df["Close"].pct_change().where(is_close_30, np.nan)
    daily_close_ret = close_ret.groupby(dates).sum()
    prev_close_ret = daily_close_ret.shift(1)
    return dates.map(prev_close_ret).astype(float)


def h_r2_lunch_dip(df):
    """ランチタイム(12:00-13:00)のリターン。5分足用。前日の値。"""
    import datetime
    t = df.index.time
    is_lunch = (t >= datetime.time(12, 0)) & (t < datetime.time(13, 0))
    dates = pd.Series([ts.date() for ts in df.index], index=df.index)
    lunch_ret = df["Close"].pct_change().where(is_lunch, np.nan)
    daily_lunch = lunch_ret.groupby(dates).sum()
    prev_lunch = daily_lunch.shift(1)
    return dates.map(prev_lunch).astype(float)


# ── ROUND2_HYPOTHESES リスト ──

# ペアマッピング（アプローチ4用）
CROSS_ASSET_PAIRS = {
    "h_r2_spy_lead": "SPY",
    "h_r2_qqq_lead": "QQQ",
    "h_r2_hyg_lead": "HYG",
    "h_r2_tlt_inverse_lead": "TLT",
}

ROUND2_HYPOTHESES: list[dict] = []

# アプローチ6: イベント
for func, fid in [
    (h_r2_event_density_7d, "R2-EV-01"),
    (h_r2_neg_event_cluster, "R2-EV-02"),
    (h_r2_geo_event_flag, "R2-EV-03"),
]:
    for direction in ["long", "short"]:
        suffix = "" if direction == "long" else "-S"
        ROUND2_HYPOTHESES.append({
            "id": f"{fid}{suffix}",
            "func": func,
            "direction": direction,
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 900,  # Round 2 exploratory
            "exploratory": True,
        })

# アプローチ5: データ駆動
for func, fid, bt in [
    (h_r2_extreme_down_reversal, "R2-DD-01", "unconditional"),
    (h_r2_vol_compression_breakout, "R2-DD-02", "unconditional"),
    (h_r2_gap_fill_tendency, "R2-DD-03", "unconditional"),
    (h_r2_friday_effect, "R2-DD-04", "unconditional"),
    (h_r2_month_start, "R2-DD-05", "unconditional"),
]:
    for direction in ["long", "short"]:
        suffix = "" if direction == "long" else "-S"
        ROUND2_HYPOTHESES.append({
            "id": f"{fid}{suffix}",
            "func": func,
            "direction": direction,
            "timeframe": "daily",
            "bias_test_type": bt,
            "requires_macro": [],
            "requires_pair": False,
            "category": 901,
            "exploratory": True,
        })

# アプローチ4: クロスアセットリード（特定ペアが必要）
for func_name, pair_sym in CROSS_ASSET_PAIRS.items():
    func = globals()[func_name]
    fid = f"R2-XA-{func_name.split('_')[2].upper()}"
    for direction in ["long", "short"]:
        suffix = "" if direction == "long" else "-S"
        ROUND2_HYPOTHESES.append({
            "id": f"{fid}{suffix}",
            "func": func,
            "direction": direction,
            "timeframe": "daily",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": True,
            "requires_pair_symbol": pair_sym,
            "category": 902,
            "exploratory": True,
        })

# アプローチ3: 時間帯特化（5分足）
for func, fid in [
    (h_r2_opening_30min_momentum, "R2-TD-01"),
    (h_r2_last_30min_momentum, "R2-TD-02"),
    (h_r2_lunch_dip, "R2-TD-03"),
]:
    for direction in ["long", "short"]:
        suffix = "" if direction == "long" else "-S"
        ROUND2_HYPOTHESES.append({
            "id": f"{fid}{suffix}",
            "func": func,
            "direction": direction,
            "timeframe": "intraday",
            "bias_test_type": "unconditional",
            "requires_macro": [],
            "requires_pair": False,
            "category": 903,
            "exploratory": True,
        })
