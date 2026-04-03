"""シグナル定義モジュール（ADR-021: Code is the Plan）

Round 1（確認ラウンド）の事前登録済みシグナル定義。
コミット後の変更は新仮説として追記のみ。既存定義は不変。

構造:
  1. ヘルパー関数（共通計算ロジック）~25個
  2. 信号生成関数（1仮説 = 1関数）
  3. HYPOTHESES リスト（Pre-Analysis Plan）

データ参照先:
  Polygon 5分足: ../master_sensei/data/research/polygon_intraday/
  日足: ../master_sensei/data/parquet/daily/
  マクロ: ../master_sensei/data/parquet/macro/
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ══════════════════════════════════════════════════════════════════════
# ヘルパー関数（共通計算ロジック）
# ══════════════════════════════════════════════════════════════════════


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI (Relative Strength Index)。

    Wilder's smoothing (exponential moving average) を使用。
    Returns: 0-100 の Series。最初の period 本は NaN。
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _sma(series: pd.Series, period: int) -> pd.Series:
    """単純移動平均。"""
    return series.rolling(period).mean()


def _ma_deviation(close: pd.Series, period: int) -> pd.Series:
    """移動平均乖離率 (%)。正 = 上方乖離、負 = 下方乖離。"""
    ma = _sma(close, period)
    return (close - ma) / ma * 100


def _bb_position(close: pd.Series, period: int = 20, n_std: float = 2.0) -> pd.Series:
    """ボリンジャーバンド内の位置。0=下限、0.5=中央、1=上限。範囲外あり。

    std=0（定数系列等）の場合は 0.5（中央）を返す。
    """
    ma = _sma(close, period)
    std = close.rolling(period).std()
    upper = ma + n_std * std
    lower = ma - n_std * std
    band_width = upper - lower
    return ((close - lower) / band_width).where(band_width > 0, 0.5)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range。"""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _gap_pct(open_: pd.Series, prev_close: pd.Series) -> pd.Series:
    """ギャップ率 (%)。正 = ギャップアップ。"""
    return (open_ - prev_close) / prev_close * 100


def _consecutive_direction(returns: pd.Series) -> pd.Series:
    """連続上昇/下落日数。正 = 連続上昇、負 = 連続下落。"""
    sign = np.sign(returns)
    groups = (sign != sign.shift()).cumsum()
    counts = sign.groupby(groups).cumcount() + 1
    return counts * sign


def _distance_from_high(close: pd.Series, period: int) -> pd.Series:
    """N日高値からの距離 (%)。常に <= 0。"""
    rolling_high = close.rolling(period).max()
    return (close - rolling_high) / rolling_high * 100


def _distance_from_low(close: pd.Series, period: int) -> pd.Series:
    """N日安値からの距離 (%)。常に >= 0。"""
    rolling_low = close.rolling(period).min()
    return (close - rolling_low) / rolling_low * 100


def _close_position_in_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """日中レンジ内の終値位置。0=安値、1=高値。"""
    range_ = high - low
    return ((close - low) / range_).where(range_ > 0, 0.5)


def _volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    """出来高比率（vs N日平均）。1.0 = 平均、2.0 = 2倍。"""
    avg = _sma(volume, period)
    return (volume / avg).where(avg > 0, 1.0)


def _vwap_deviation_pct(close: pd.Series, vwap: pd.Series) -> pd.Series:
    """VWAP乖離率 (%)。正 = VWAPより上。"""
    return (close - vwap) / vwap * 100


def _price_volume_divergence(returns: pd.Series, volume_change: pd.Series) -> pd.Series:
    """価格-出来高ダイバージェンス。符号が異なれば True。"""
    return (np.sign(returns) != np.sign(volume_change))


def _realized_vol(returns: pd.Series, period: int = 20) -> pd.Series:
    """実現ボラティリティ（年率換算）。"""
    return returns.rolling(period).std() * np.sqrt(252)


def _drawdown_from_peak(close: pd.Series) -> pd.Series:
    """ピークからのドローダウン (%)。常に <= 0。"""
    peak = close.cummax()
    return (close - peak) / peak * 100


def _n_day_return(close: pd.Series, n: int = 1) -> pd.Series:
    """N日リターン (%)。"""
    return close.pct_change(n) * 100


def _bull_bear_spread(bull_returns: pd.Series, bear_returns: pd.Series) -> pd.Series:
    """Bull/Bear日次リターン差。理論値0、正ならBull有利。"""
    return bull_returns + bear_returns  # Bear returns are negative when Bull is positive


def _avg_trade_size(volume: pd.Series, num_trades: pd.Series) -> pd.Series:
    """平均取引サイズ (volume / num_trades)。"""
    return (volume / num_trades).where(num_trades > 0, np.nan)


def _vn_divergence(volume: pd.Series, num_trades: pd.Series, period: int = 20) -> pd.Series:
    """出来高スパイク vs 取引回数スパイクの乖離。

    正 = 出来高スパイクが取引回数スパイクより大きい（大口参入の示唆）。
    負 = 取引回数スパイクが出来高スパイクより大きい（小口パニックの示唆）。
    """
    v_ratio = _volume_ratio(volume, period)
    n_ratio = _volume_ratio(num_trades, period)
    return v_ratio - n_ratio


def _bar_vwap_deviation(close: pd.Series, vwap: pd.Series) -> pd.Series:
    """バー内VWAP乖離。正 = バー後半で買い圧力。"""
    return close - vwap


def _day_of_week(index: pd.DatetimeIndex) -> pd.Series:
    """曜日（0=月曜、4=金曜）。"""
    return pd.Series(index.dayofweek, index=index)


def _is_month_boundary(index: pd.DatetimeIndex, days: int = 2) -> pd.Series:
    """月末/月初の days 日以内なら True。"""
    dom = index.day
    days_in_month = index.days_in_month
    return pd.Series(
        (dom <= days) | (dom >= days_in_month - days + 1),
        index=index,
    )


def _vix_term_structure(vix: pd.Series, vix3m: pd.Series) -> pd.Series:
    """VIX期間構造（VIX/VIX3M比率）。>1=バックワーデーション（短期恐怖優位）。"""
    return (vix / vix3m).where(vix3m > 0, np.nan)


def _vix_spike(vix: pd.Series, threshold_pct: float = 10.0) -> pd.Series:
    """VIXスパイク検出。前日比がthreshold_pct超でTrue。"""
    vix_change = vix.pct_change() * 100
    return vix_change > threshold_pct


def _stress_days(series: pd.Series, level: float) -> pd.Series:
    """指定水準超の連続日数。seriesがlevel超の日をカウント。"""
    above = series > level
    # above が変わるたびに新グループ
    groups = (above != above.shift()).cumsum()
    counts = above.groupby(groups).cumcount() + 1
    return counts.where(above, 0)


# ══════════════════════════════════════════════════════════════════════
# 信号生成関数（1仮説 = 1関数）
# ══════════════════════════════════════════════════════════════════════

# ── Cat 1: 価格パターン ──


def h_01_01(df):
    """ギャップ率 (%)。正=ギャップアップ。"""
    return _gap_pct(df['Open'], df['Close'].shift(1))


def h_01_02(df):
    """連続上昇/下落日数。正=連続上昇、負=連続下落。"""
    return _consecutive_direction(df['Close'].pct_change())


def h_01_03a(df):
    """5日高値からの距離 (%)。"""
    return _distance_from_high(df['Close'], 5)


def h_01_03b(df):
    """10日高値からの距離 (%)。"""
    return _distance_from_high(df['Close'], 10)


def h_01_03c(df):
    """20日高値からの距離 (%)。"""
    return _distance_from_high(df['Close'], 20)


def h_01_03d(df):
    """50日高値からの距離 (%)。"""
    return _distance_from_high(df['Close'], 50)


def h_01_03e(df):
    """5日安値からの距離 (%)。"""
    return _distance_from_low(df['Close'], 5)


def h_01_03f(df):
    """10日安値からの距離 (%)。"""
    return _distance_from_low(df['Close'], 10)


def h_01_03g(df):
    """20日安値からの距離 (%)。"""
    return _distance_from_low(df['Close'], 20)


def h_01_03h(df):
    """50日安値からの距離 (%)。"""
    return _distance_from_low(df['Close'], 50)


def h_01_04a(df):
    """5日MA乖離率 (%)。"""
    return _ma_deviation(df['Close'], 5)


def h_01_04b(df):
    """10日MA乖離率 (%)。"""
    return _ma_deviation(df['Close'], 10)


def h_01_04c(df):
    """20日MA乖離率 (%)。"""
    return _ma_deviation(df['Close'], 20)


def h_01_04d(df):
    """50日MA乖離率 (%)。"""
    return _ma_deviation(df['Close'], 50)


def h_01_05a(df):
    """RSI 7日。"""
    return _rsi(df['Close'], 7)


def h_01_05b(df):
    """RSI 14日。"""
    return _rsi(df['Close'], 14)


def h_01_06(df):
    """ボリンジャーバンド内位置 (0-1)。"""
    return _bb_position(df['Close'], 20, 2.0)


def h_01_07(df):
    """ATR比率（当日ATR / 14日平均ATR）。"""
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift(1)).abs(),
        (df['Low'] - df['Close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr_14 = _atr(df['High'], df['Low'], df['Close'], 14)
    return (tr / atr_14).where(atr_14 > 0, np.nan)


def h_01_08(df):
    """日中レンジ / ATR比率。1超=平均より広いレンジ。"""
    intraday_range = df['High'] - df['Low']
    atr_14 = _atr(df['High'], df['Low'], df['Close'], 14)
    return (intraday_range / atr_14).where(atr_14 > 0, np.nan)


def h_01_09(df):
    """Opening Range位置: 終値の開場60分高安レンジ内位置 (0-1)。5分足専用。

    最初の12本(60分)でOR確定。13本目以降のみ有効値。
    それ以前はNaN（Look-Ahead Bias防止）。
    """
    if 'VWAP' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    dates = df.index.date
    date_series = pd.Series(dates, index=df.index)
    or_high = df.groupby(date_series)['High'].transform(
        lambda x: x.iloc[:12].max() if len(x) >= 12 else np.nan
    )
    or_low = df.groupby(date_series)['Low'].transform(
        lambda x: x.iloc[:12].min() if len(x) >= 12 else np.nan
    )
    # 各日のバー番号（0始まり）。12本目以前はNaN
    bar_in_day = df.groupby(date_series).cumcount()
    rng = or_high - or_low
    result = ((df['Close'] - or_low) / rng).where(rng > 0, 0.5)
    return result.where(bar_in_day >= 12, np.nan)


def h_01_10(df):
    """日中レンジ内の終値位置 (0-1)。0=安値、1=高値。"""
    return _close_position_in_range(df['High'], df['Low'], df['Close'])


# ── Cat 2: 出来高 ──


def h_02_01a(df):
    """出来高比率 vs 5日平均。"""
    return _volume_ratio(df['Volume'], 5)


def h_02_01b(df):
    """出来高比率 vs 10日平均。"""
    return _volume_ratio(df['Volume'], 10)


def h_02_01c(df):
    """出来高比率 vs 20日平均。"""
    return _volume_ratio(df['Volume'], 20)


def h_02_02(df):
    """出来高トレンド: 5日出来高MA / 20日出来高MA。1超=増加傾向。"""
    vol_5 = _sma(df['Volume'], 5)
    vol_20 = _sma(df['Volume'], 20)
    return (vol_5 / vol_20).where(vol_20 > 0, np.nan)


def h_02_03(df):
    """価格-出来高ダイバージェンス。True=符号不一致。"""
    returns = df['Close'].pct_change()
    vol_change = df['Volume'].pct_change()
    return _price_volume_divergence(returns, vol_change)


def h_02_04(df):
    """時間帯別相対出来高: 当バーの出来高 / 同時間帯平均出来高。5分足専用。"""
    if 'VWAP' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    time_of_day = df.index.time
    time_avg = df.groupby(time_of_day)['Volume'].transform('mean')
    return (df['Volume'] / time_avg).where(time_avg > 0, np.nan)


def h_02_05(df):
    """VWAP乖離率 (%)。5分足専用。"""
    if 'VWAP' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return _vwap_deviation_pct(df['Close'], df['VWAP'])


# ── Cat 3: ボラティリティ ──
# requires_macro: ["VIX"] or ["VIX", "VIX3M"]
# runner が df['vix'], df['vix3m'] 等をマージする前提


def h_03_01(df):
    """VIX水準。"""
    return df['vix']


def h_03_02(df):
    """VIX日次変化量 (%)。"""
    return df['vix'].pct_change() * 100


def h_03_03(df):
    """VIX期間構造（VIX/VIX3M比率）。>1=バックワーデーション。"""
    return _vix_term_structure(df['vix'], df['vix3m'])


def h_03_04(df):
    """VIX期間構造の日次変化（前日比）。"""
    ts = _vix_term_structure(df['vix'], df['vix3m'])
    return ts.diff()


def h_03_05(df):
    """実現Vol - VIX差。正=実現Volが高い（Volが過小評価されている）。"""
    rv = _realized_vol(df['Close'].pct_change(), 20)
    return rv - df['vix']


def h_03_06(df):
    """ATR変化率: 当日ATR / 5日前ATR - 1。正=ボラ加速。"""
    atr_14 = _atr(df['High'], df['Low'], df['Close'], 14)
    return (atr_14 / atr_14.shift(5) - 1).where(atr_14.shift(5) > 0, np.nan)


def h_03_07(df):
    """日中ボラティリティ: 前日の5分足リターン標準偏差。5分足専用。

    Look-Ahead Bias防止: 当日ではなく前営業日の日中Volを使用。
    """
    if 'VWAP' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    returns = df['Close'].pct_change()
    dates = pd.Series(df.index.date, index=df.index)
    daily_vol = returns.groupby(dates).transform('std')
    # 前日の値を使用: 各日の値を1日分シフト
    unique_dates = dates.unique()
    date_to_vol = daily_vol.groupby(dates).last()
    prev_vol = date_to_vol.shift(1)
    return dates.map(prev_vol).astype(float)


# ── Cat 8: センチメント ──
# requires_macro: ["VIX", "VIX3M"]
# VIXY用: requires_pair: "VIXY"


def h_08_01(df):
    """VIX期間構造 as センチメント。バックワーデーション=短期恐怖優位。h_03_03と同一計算。"""
    return _vix_term_structure(df['vix'], df['vix3m'])


def h_08_02(df):
    """VIXY出来高比率 as リテールセンチメント。pair_Volume=VIXY出来高。"""
    if 'pair_Volume' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return _volume_ratio(df['pair_Volume'], 20)


def h_08_03(df):
    """VIXY価格変動 vs VIX変動の乖離。正=VIXYがVIXより過剰反応。"""
    if 'pair_Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    vixy_ret = df['pair_Close'].pct_change() * 100
    vix_change = df['vix'].pct_change() * 100
    return vixy_ret - vix_change


# ── Cat 4: クロスアセット ──
# requires_macro: 各指標名


def h_04_01a(df):
    """Brent原油水準。"""
    return df['brent']


def h_04_01b(df):
    """Brent原油日次変化 (%)。"""
    return df['brent'].pct_change() * 100


def h_04_02a(df):
    """HYスプレッド水準。"""
    return df['hy_spread']


def h_04_02b(df):
    """HYスプレッド日次変化。"""
    return df['hy_spread'].diff()


def h_04_03a(df):
    """イールドカーブ水準。"""
    return df['yield_curve']


def h_04_03b(df):
    """イールドカーブ日次変化。"""
    return df['yield_curve'].diff()


def h_04_04a(df):
    """USD Index水準。"""
    return df['usd_index']


def h_04_04b(df):
    """USD Index日次変化 (%)。"""
    return df['usd_index'].pct_change() * 100


def h_04_05a(df):
    """US10Y水準。"""
    return df['us10y']


def h_04_05b(df):
    """US10Y日次変化。"""
    return df['us10y'].diff()


# ── Cat 5: カレンダー/行動ファイナンス ──


def h_05_01(df):
    """曜日（0=月〜4=金）。"""
    return _day_of_week(df.index)


def h_05_02(df):
    """月末/月初フラグ（最終2日+最初2日）。"""
    return _is_month_boundary(df.index, 2)


def h_05_03(df):
    """月次季節性: 月番号（1-12）。"""
    return pd.Series(df.index.month, index=df.index)


def h_05_04(df):
    """オーバーナイトギャップ率 (%)。"""
    return _gap_pct(df['Open'], df['Close'].shift(1))


def h_05_05(df):
    """オーバーナイトギャップの絶対値 (%)。大きさのみ。"""
    return _gap_pct(df['Open'], df['Close'].shift(1)).abs()


# ── Cat 9: 古典手法の現代適用 ──


def h_09_01(df):
    """Wyckoff Effort vs Result: 出来高大+価格変化小の検出。

    ratio = |return| / volume_ratio。小さいほど「吸収」（大出来高だが動かない）。
    """
    ret = df['Close'].pct_change().abs() * 100
    vol_r = _volume_ratio(df['Volume'], 20)
    return (ret / vol_r).where(vol_r > 0, np.nan)


def h_09_02(df):
    """スプリング検出: 20日安値を下回った後に反発。

    前日に20日安値以下 → 当日終値が20日安値より上 → True。
    """
    low_20 = df['Close'].rolling(20).min()
    below_yesterday = df['Close'].shift(1) <= low_20.shift(1)
    above_today = df['Close'] > low_20
    return below_yesterday & above_today


def h_09_03(df):
    """アップスラスト検出: 20日高値を上回った後に反落。

    前日に20日高値以上 → 当日終値が20日高値より下 → True。
    """
    high_20 = df['Close'].rolling(20).max()
    above_yesterday = df['Close'].shift(1) >= high_20.shift(1)
    below_today = df['Close'] < high_20
    return above_yesterday & below_today


# ── Cat 11: 相対シグナル ──
# requires_pair: 対象ペアシンボル


def h_11_01(df):
    """SOXL/TQQQ比率の変動。pair_Close=TQQQの終値。"""
    if 'pair_Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    ratio = df['Close'] / df['pair_Close']
    return ratio.pct_change() * 100


def h_11_02(df):
    """Bull/Bear乖離率: 自シンボルリターン vs -1*ペアリターンの差。"""
    if 'pair_Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    self_ret = df['Close'].pct_change() * 100
    pair_ret = df['pair_Close'].pct_change() * 100
    return self_ret + pair_ret  # Bull+Bear: 理論上0、正ならBull有利


def h_11_03(df):
    """レバETF間モメンタム格差: 自シンボル5日リターン - ペア5日リターン。"""
    if 'pair_Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    self_mom = _n_day_return(df['Close'], 5)
    pair_mom = _n_day_return(df['pair_Close'], 5)
    return self_mom - pair_mom


# ── Cat 12: クロスタイムフレーム ──


def h_12_01(df):
    """週足モメンタム: 5日リターン。日足で算出する週足代替。"""
    return _n_day_return(df['Close'], 5)


def h_12_02(df):
    """日足→日中方向一致: 前日リターンの符号。5分足に日足方向を伝搬。"""
    dates = pd.Series(df.index.date, index=df.index)
    daily_ret = df.groupby(dates)['Close'].transform('last').pct_change()
    return daily_ret.shift(1).apply(np.sign)


def h_12_03(df):
    """多TF一致度: 1日リターンと5日リターンの符号一致。True=一致。"""
    ret_1 = _n_day_return(df['Close'], 1)
    ret_5 = _n_day_return(df['Close'], 5)
    return (np.sign(ret_1) == np.sign(ret_5))


# ── Cat 13: レジーム遷移 ──
# requires_macro: ["VIX"]


def h_13_01(df):
    """リスクオフ→リスクオン変化: VIXの5日変化率 (%)。負=改善。"""
    return df['vix'].pct_change(5) * 100


def h_13_02(df):
    """VIXレジーム切替速度: VIXの1日変化率 vs 5日変化率の比。急変度。"""
    d1 = df['vix'].pct_change() * 100
    d5 = df['vix'].pct_change(5) * 100
    return (d1 / d5).where(d5.abs() > 0.01, np.nan)


def h_13_03(df):
    """レジーム滞在日数: VIX>25の連続日数。"""
    return _stress_days(df['vix'], 25.0)


# ── Cat 14: 予測可能フロー/構造イベント ──


def h_14_01(df):
    """OpEx週フラグ: 月の第3金曜を含む週。"""
    # 第3金曜 = day 15-21 のうち金曜日
    dom = df.index.day
    dow = df.index.dayofweek
    third_friday = (dom >= 15) & (dom <= 21) & (dow == 4)
    # その週（月-金）全体をフラグ
    # 簡易実装: 第3金曜の週番号と一致
    week_num = df.index.isocalendar().week.values
    opex_weeks = pd.Series(week_num, index=df.index).where(third_friday).ffill().bfill()
    return pd.Series(week_num, index=df.index) == opex_weeks


def h_14_02(df):
    """四半期末フラグ: 3,6,9,12月の最終5営業日。"""
    month = df.index.month
    dom = df.index.day
    dim = df.index.days_in_month
    is_quarter_end_month = month.isin([3, 6, 9, 12])
    is_last_5_days = dom >= dim - 6  # 余裕を持って6日前から
    return pd.Series(is_quarter_end_month & is_last_5_days, index=df.index)


def h_14_03(df):
    """月末リバランスフロー方向推定: 月末5日の出来高比率。"""
    is_month_end = _is_month_boundary(df.index, 3)
    vol_ratio = _volume_ratio(df['Volume'], 20)
    return vol_ratio.where(is_month_end, np.nan)


# ── Cat 17: 伝播遅延（リード・ラグ）──
# requires_macro: 各指標


def h_17_01a(df):
    """Brent→ETFラグ1日: 前日のBrent変化率。"""
    return df['brent'].pct_change().shift(1) * 100


def h_17_01b(df):
    """Brent→ETFラグ2日: 2日前のBrent変化率。"""
    return df['brent'].pct_change().shift(2) * 100


def h_17_02a(df):
    """VIX→ETFラグ1日: 前日のVIX変化率。"""
    return df['vix'].pct_change().shift(1) * 100


def h_17_02b(df):
    """HYスプレッド→ETFラグ1日: 前日のHYスプレッド変化。"""
    return df['hy_spread'].diff().shift(1)


# ── Cat 18: ノートレード条件 ──
# requires_macro: ["VIX"]


def h_18_01(df):
    """VIX極端値 (>35) フラグ。True=ノートレード推奨。"""
    return df['vix'] > 35


def h_18_02(df):
    """出来高異常低フラグ: 20日平均の50%未満。"""
    return _volume_ratio(df['Volume'], 20) < 0.5


def h_18_03(df):
    """連続損失フラグ: 3日連続下落。"""
    consec = _consecutive_direction(df['Close'].pct_change())
    return consec <= -3


def h_18_04(df):
    """VIXスパイクフラグ: 前日比+20%超。"""
    return _vix_spike(df['vix'], 20.0)


# ── Cat 6: レバETF固有 ──
# requires_pair: Bear側シンボル


def h_06_01(df):
    """Bull/Bearペアスプレッド: 自シンボル + ペアの日次リターン。理論0。"""
    if 'pair_Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return _bull_bear_spread(
        df['Close'].pct_change() * 100,
        df['pair_Close'].pct_change() * 100,
    )


def h_06_02(df):
    """ボラティリティ・ディケイ推定: 5日累積リターン vs 5日単純和の差。"""
    daily_ret = df['Close'].pct_change()
    # 累積 = (1+r1)(1+r2)...-1、単純和 = r1+r2+...
    cum_5 = (1 + daily_ret).rolling(5).apply(np.prod, raw=True) - 1
    sum_5 = daily_ret.rolling(5).sum()
    return (cum_5 - sum_5) * 100  # ディケイ量 (%)


def h_06_03(df):
    """引け前リバランスフロー推定: 日次変動幅が大きい日ほどフロー大。"""
    daily_abs_ret = df['Close'].pct_change().abs() * 100
    return daily_abs_ret  # 大きいほどリバランス量が大きい


def h_06_04(df):
    """インバースETFプレミアム/ディスカウント: Bull/Bear理論比率との乖離。"""
    if 'pair_Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    # Bull日次ret ≈ -Bear日次retなら理論通り。乖離=プレミアム
    bull_ret = df['Close'].pct_change()
    bear_ret = df['pair_Close'].pct_change()
    return (bull_ret + bear_ret) * 100


# ── Cat 7: レジーム切替メタ戦略 ──
# requires_macro: ["VIX", "VIX3M"]


def h_07_01(df):
    """VIXレジーム: 高VIX(>25)フラグ。"""
    return df['vix'] > 25


def h_07_02(df):
    """VIXレジーム: 低VIX(<15)フラグ。"""
    return df['vix'] < 15


def h_07_03(df):
    """VIX期間構造バックワーデーション: VIX/VIX3M > 1。"""
    return _vix_term_structure(df['vix'], df['vix3m']) > 1


def h_07_04(df):
    """レジーム遷移検出: VIXが25を上抜け（前日<=25、当日>25）。"""
    return (df['vix'].shift(1) <= 25) & (df['vix'] > 25)


def h_07_05(df):
    """全指標統合レジームスコア: VIX + HYスプレッド + Brent変化の合成。"""
    vix_z = (df['vix'] - df['vix'].rolling(20).mean()) / df['vix'].rolling(20).std()
    hy_z = (df['hy_spread'] - df['hy_spread'].rolling(20).mean()) / df['hy_spread'].rolling(20).std()
    brent_ret = df['brent'].pct_change(5) * 100
    brent_z = (brent_ret - brent_ret.rolling(20).mean()) / brent_ret.rolling(20).std()
    return (vix_z + hy_z + brent_z) / 3


# ── Cat 19: 方向切替戦略 ──


def h_19_01(df):
    """方向切替: 5日MAの傾き。正=ロング、負=ショート。"""
    ma5 = _sma(df['Close'], 5)
    return ma5.diff()


def h_19_02(df):
    """方向切替: RSI(14)の50超/以下。50超=ロング方向。"""
    return _rsi(df['Close'], 14) - 50


# ── Cat 20: 方向予測不要戦略 ──


def h_20_01(df):
    """Bull/Bearペアディケイ率: 5日rolling Bull+Bear累積リターン。"""
    if 'pair_Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    bull_cum = (1 + df['Close'].pct_change()).rolling(5).apply(np.prod, raw=True) - 1
    bear_cum = (1 + df['pair_Close'].pct_change()).rolling(5).apply(np.prod, raw=True) - 1
    return (bull_cum + bear_cum) * 100  # 両方持つとディケイ分だけ減る


def h_20_02(df):
    """追跡誤差の非対称性: |Bull日次ret| - |Bear日次ret|。"""
    if 'pair_Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df['Close'].pct_change().abs() - df['pair_Close'].pct_change().abs()


def h_20_03(df):
    """方向予測不要: ATR変化のみでボラティリティ予測。方向不問。"""
    atr_14 = _atr(df['High'], df['Low'], df['Close'], 14)
    return atr_14.pct_change(5) * 100


# ── Cat 23: Bull/Bear追跡誤差の非対称性 ──


def h_23_01(df):
    """上昇日vs下落日のBull/Bear乖離: 上昇日のBull+Bear vs 下落日のBull+Bear。"""
    if 'pair_Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    spread = _bull_bear_spread(
        df['Close'].pct_change() * 100,
        df['pair_Close'].pct_change() * 100,
    )
    return spread  # 上昇日で正ならBull優位


def h_23_02(df):
    """累積追跡誤差: Bull+Bearの20日累積差。"""
    if 'pair_Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    daily_spread = df['Close'].pct_change() + df['pair_Close'].pct_change()
    return daily_spread.rolling(20).sum() * 100


# ── Cat 24: リバランスフィードバックループ検出 ──


def h_24_01(df):
    """フィードバック強度: 日次|リターン| > 5%の日の連続数。"""
    big_move = df['Close'].pct_change().abs() > 0.05
    groups = (big_move != big_move.shift()).cumsum()
    counts = big_move.groupby(groups).cumcount() + 1
    return counts.where(big_move, 0)


def h_24_02(df):
    """リバランス増幅: 当日|リターン| > 前日|リターン|が連続するか。"""
    abs_ret = df['Close'].pct_change().abs()
    increasing = abs_ret > abs_ret.shift(1)
    groups = (increasing != increasing.shift()).cumsum()
    counts = increasing.groupby(groups).cumcount() + 1
    return counts.where(increasing, 0)


# ── Cat 25: 日中マイクロパターン崩壊検出 ──


def h_25_01(df):
    """日中出来高パターン崩壊: 中盤(バー25-55)の出来高比率。5分足専用。

    通常U字型なので中盤は低い。中盤出来高比率が高い=パターン崩壊。
    """
    if 'VWAP' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    bar_in_day = df.groupby(df.index.date).cumcount()
    is_midday = (bar_in_day >= 25) & (bar_in_day <= 55)
    dates = pd.Series(df.index.date, index=df.index)
    day_avg_vol = df.groupby(dates)['Volume'].transform('mean')
    midday_ratio = (df['Volume'] / day_avg_vol).where(day_avg_vol > 0, np.nan)
    return midday_ratio.where(is_midday, np.nan)


def h_25_02(df):
    """日中パターン崩壊検出: 実際の出来高分布と理論U字型の乖離度。5分足専用。"""
    if 'VWAP' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    time_of_day = df.index.time
    time_avg = df.groupby(time_of_day)['Volume'].transform('mean')
    # 時間帯平均からの乖離の絶対値（大きい=パターン崩壊）
    return ((df['Volume'] - time_avg) / time_avg).abs().where(time_avg > 0, np.nan)


# ── Cat 26: 1ルール戦略ベースライン ──


def h_26_01(df):
    """ベースライン: VIX>30なら買わない（True=ノートレード）。"""
    return df['vix'] > 30


def h_26_02(df):
    """ベースライン: 前日-3%超なら翌日ロング。"""
    return _n_day_return(df['Close'], 1).shift(1) < -3.0


def h_26_03(df):
    """ベースライン: RSI(14)<30なら買い。"""
    return _rsi(df['Close'], 14) < 30


# ── Cat 27: 極端条件限定戦略 ──


def h_27_01(df):
    """極端条件: σ偏差-2以下 + VIX>25 の同時発生。"""
    ret = df['Close'].pct_change()
    z = (ret - ret.rolling(20).mean()) / ret.rolling(20).std()
    return (z < -2) & (df['vix'] > 25)


def h_27_02(df):
    """極端条件: VIXスパイク + 出来高2倍超の同時発生。"""
    vix_sp = _vix_spike(df['vix'], 15.0)
    vol_sp = _volume_ratio(df['Volume'], 20) > 2.0
    return vix_sp & vol_sp


def h_27_03(df):
    """極端条件: 3日連続下落 + VIX>25。"""
    consec = _consecutive_direction(df['Close'].pct_change())
    return (consec <= -3) & (df['vix'] > 25)


# ── Cat 28: 純粋マクロ戦略 ──


def h_28_01(df):
    """純粋マクロ: VIX + HYスプレッドのZスコア合成。"""
    vix_z = (df['vix'] - df['vix'].rolling(20).mean()) / df['vix'].rolling(20).std()
    hy_z = (df['hy_spread'] - df['hy_spread'].rolling(20).mean()) / df['hy_spread'].rolling(20).std()
    return (vix_z + hy_z) / 2


def h_28_02(df):
    """純粋マクロ: 全マクロ指標の正常/異常カウント。"""
    vix_abnormal = (df['vix'] > 25) | (df['vix'] < 12)
    hy_abnormal = df['hy_spread'] > 4.0
    yc_abnormal = df['yield_curve'] < 0
    count = vix_abnormal.astype(int) + hy_abnormal.astype(int) + yc_abnormal.astype(int)
    return count


# ── Cat 29: 減衰振動モデル ──


def h_29_01(df):
    """急落後リバウンド: 日次-5%超の翌日。direction_fixed=long。"""
    return _n_day_return(df['Close'], 1).shift(1) < -5.0


def h_29_02(df):
    """減衰振動: 急落後N日の|リターン|の減衰。2日目|ret| < 1日目|ret|ならTrue。"""
    abs_ret = _n_day_return(df['Close'], 1).abs()
    return abs_ret < abs_ret.shift(1)


# ── Cat 30: 予測可能フローカレンダー（統合）──


def h_30_01(df):
    """OpEx週: h_14_01と同一。重複管理のため参照。"""
    return h_14_01(df)


def h_30_02(df):
    """四半期末: h_14_02と同一。"""
    return h_14_02(df)


def h_30_03(df):
    """月末月初: h_05_02と同一。"""
    return _is_month_boundary(df.index, 2)


# ── Cat 32: 動的閾値（Vol連動パラメータ）──


def h_32_01(df):
    """動的RSI oversold: VIX>25時はRSI<20、それ以外はRSI<30。"""
    rsi_14 = _rsi(df['Close'], 14)
    threshold = pd.Series(30.0, index=df.index)
    threshold = threshold.where(df['vix'] <= 25, 20.0)
    return rsi_14 < threshold


def h_32_02(df):
    """動的RSI overbought: VIX>25時はRSI>80、それ以外はRSI>70。"""
    rsi_14 = _rsi(df['Close'], 14)
    threshold = pd.Series(70.0, index=df.index)
    threshold = threshold.where(df['vix'] <= 25, 80.0)
    return rsi_14 > threshold


def h_32_03(df):
    """動的BB幅: VIXに応じてBBのstd倍率を変更。高VIX=3σ、低VIX=2σ。"""
    n_std = pd.Series(2.0, index=df.index)
    n_std = n_std.where(df['vix'] <= 25, 3.0)
    # バーごとに異なるn_stdを使うためループ
    # 簡易実装: 2σと3σの2つを計算し条件で選択
    bb_2 = _bb_position(df['Close'], 20, 2.0)
    bb_3 = _bb_position(df['Close'], 20, 3.0)
    return bb_2.where(df['vix'] <= 25, bb_3)


def h_32_04(df):
    """動的出来高スパイク閾値: VIX>25時は1.5倍、それ以外は2倍。"""
    vol_r = _volume_ratio(df['Volume'], 20)
    threshold = pd.Series(2.0, index=df.index).where(df['vix'] <= 25, 1.5)
    return vol_r > threshold


def h_32_05(df):
    """動的MA乖離閾値: ATRに連動した乖離率閾値。"""
    dev = _ma_deviation(df['Close'], 20)
    atr_pct = _atr(df['High'], df['Low'], df['Close'], 14) / df['Close'] * 100
    return dev / atr_pct  # ATRで正規化した乖離率


# ── Cat 33: 強制フロー/カウンターパーティ分析 ──


def h_33_01(df):
    """マージンコール推定: VIX急騰+出来高急増の同時発生。"""
    vix_sp = df['vix'].pct_change() > 0.1  # VIX +10%
    vol_sp = _volume_ratio(df['Volume'], 20) > 1.5
    return vix_sp & vol_sp


def h_33_02(df):
    """ETFリバランス規模推定: 日次|変動|に比例。"""
    return df['Close'].pct_change().abs() * df['Volume']


def h_33_03(df):
    """OpEx強制フロー: OpEx週 + 出来高異常の組合せ。"""
    opex = h_14_01(df)
    vol_spike = _volume_ratio(df['Volume'], 20) > 1.5
    return opex & vol_spike


# ── Cat 34: レバETF日中NAV乖離パターン ──


def h_34_01(df):
    """Bull/Bear理論比率との乖離: 日次ベース。"""
    if 'pair_Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    bull_ret = df['Close'].pct_change()
    bear_ret = df['pair_Close'].pct_change()
    # 理論: bear_ret ≈ -3 * (bull_ret / 3) = -bull_ret (for 3x)
    # 乖離 = bear_ret + bull_ret (理論0)
    return (bull_ret + bear_ret) * 100


def h_34_02(df):
    """Bull/Bear比率の日中変動: 5分足ベース。"""
    if 'pair_Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    ratio = df['Close'] / df['pair_Close']
    return ratio.pct_change() * 100


# ── Cat 35: 持続ストレス期間 ──


def h_35_01(df):
    """VIX>25の連続日数。"""
    return _stress_days(df['vix'], 25.0)


def h_35_02(df):
    """VIX>30の連続日数。"""
    return _stress_days(df['vix'], 30.0)


def h_35_03(df):
    """HYスプレッド>4の連続日数。"""
    return _stress_days(df['hy_spread'], 4.0)


# ── Cat 37: 恐怖の時間減衰 ──


def h_37_01(df):
    """VIXスパイク(+15%)からの経過日数。direction_fixed=long。"""
    spike = _vix_spike(df['vix'], 15.0)
    # スパイク後の経過日数をカウント
    groups = spike.cumsum()
    elapsed = spike.groupby(groups).cumcount()
    return elapsed.where(groups > 0, np.nan)


def h_37_02(df):
    """VIXスパイク(+20%)からの経過日数。direction_fixed=long。"""
    spike = _vix_spike(df['vix'], 20.0)
    groups = spike.cumsum()
    elapsed = spike.groupby(groups).cumcount()
    return elapsed.where(groups > 0, np.nan)


# ── Cat 40: ストップハンティング水準の逆用 ──


def h_40_01(df):
    """直近20日安値割れ後の反発候補。日足安値ブレイク。"""
    low_20 = df['Low'].rolling(20).min()
    return df['Low'] < low_20.shift(1)


def h_40_02(df):
    """ラウンドナンバー($10刻み)付近でのヒゲ。"""
    nearest_round = (df['Close'] / 10).round() * 10
    distance_pct = (df['Close'] - nearest_round).abs() / df['Close'] * 100
    return distance_pct  # 小さいほどラウンドナンバー近傍


# ── Cat 41: ドローダウン非線形性 ──


def h_41_01(df):
    """ドローダウン深度 (%)。ピークからの下落率。"""
    return _drawdown_from_peak(df['Close'])


def h_41_02(df):
    """ドローダウン加速度: ドローダウンの日次変化。負=悪化加速。"""
    dd = _drawdown_from_peak(df['Close'])
    return dd.diff()


# ── Cat 42: 出来高渋滞とブレイクアウト加速度 ──


def h_42_01(df):
    """価格渋滞検出: 5日間の価格レンジ / ATR。小さい=渋滞。"""
    range_5 = df['High'].rolling(5).max() - df['Low'].rolling(5).min()
    atr_14 = _atr(df['High'], df['Low'], df['Close'], 14)
    return (range_5 / atr_14).where(atr_14 > 0, np.nan)


def h_42_02(df):
    """ブレイクアウト加速度: 渋滞(h_42_01<1)後の1日リターン絶対値。"""
    congestion = h_42_01(df) < 1.0
    ret_abs = _n_day_return(df['Close'], 1).abs()
    return ret_abs.where(congestion.shift(1), np.nan)


# ── Cat 43: 複合異常スコア ──


def h_43_01(df):
    """複合異常スコア: 正常範囲外の指標数 (0-5)。"""
    vix_abn = ((df['vix'] > 30) | (df['vix'] < 12)).astype(int)
    hy_abn = (df['hy_spread'] > 4.5).astype(int)
    yc_abn = (df['yield_curve'] < -0.2).astype(int)
    brent_abn = (df['brent'].pct_change(5).abs() > 0.1).astype(int)
    us10y_abn = (df['us10y'].diff(5).abs() > 0.3).astype(int)
    return vix_abn + hy_abn + yc_abn + brent_abn + us10y_abn


def h_43_02(df):
    """異常状態の持続日数: 異常スコア>=2の連続日数。"""
    score = h_43_01(df)
    return _stress_days(score, 1.5)  # >=2 を > 1.5 で検出


# ── Cat 44: 偽の回復検出 ──


def h_44_01(df):
    """VIX急落+HYスプレッド高止まり: 偽の安心検出。"""
    vix_down = df['vix'].pct_change(3) < -0.1  # VIX 3日で-10%
    hy_still_high = df['hy_spread'] > df['hy_spread'].rolling(20).mean()
    return vix_down & hy_still_high


def h_44_02(df):
    """複数指標の回復タイミングずれ: VIXは正常だがHYはまだ高い。"""
    vix_normal = df['vix'] < 20
    hy_elevated = df['hy_spread'] > 3.5
    return vix_normal & hy_elevated


# ── Cat 46: Bull/Bear出来高比率の振動周期 ──


def h_46_01(df):
    """Bull/Bear出来高比率。pair_Volume=Bear出来高。"""
    if 'pair_Volume' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return (df['Volume'] / df['pair_Volume']).where(df['pair_Volume'] > 0, np.nan)


def h_46_02(df):
    """Bull/Bear出来高比率の5日変化率。"""
    ratio = h_46_01(df)
    return ratio.pct_change(5) * 100


# ── Cat 50: 市場サイクル位置推定 ──


def h_50_01(df):
    """VIXスパイクからの経過日数（最大値クリップなし）。サイクル位相。"""
    spike = df['vix'] > df['vix'].rolling(60).mean() + 2 * df['vix'].rolling(60).std()
    groups = spike.cumsum()
    elapsed = spike.groupby(groups).cumcount()
    return elapsed.where(groups > 0, np.nan)


def h_50_02(df):
    """60日窓でのVIX位置: 0=60日最低、1=60日最高。"""
    v = df['vix']
    low_60 = v.rolling(60).min()
    high_60 = v.rolling(60).max()
    rng = high_60 - low_60
    return ((v - low_60) / rng).where(rng > 0, 0.5)


def h_50_03(df):
    """サイクルフェーズ: VIX上昇中(1) vs 下降中(-1)。5日MA方向。"""
    vix_ma = _sma(df['vix'], 5)
    return np.sign(vix_ma.diff())


# ── Cat 53: 市場リズム変調検出 ──


def h_53_01(df):
    """実現Vol安定度: 20日実現Volの5日変化率。大きい=リズム変調。"""
    rv = _realized_vol(df['Close'].pct_change(), 20)
    return rv.pct_change(5).abs() * 100


def h_53_02(df):
    """出来高パターン安定度: 出来高の20日rolling CV(変動係数)。"""
    vol_mean = _sma(df['Volume'], 20)
    vol_std = df['Volume'].rolling(20).std()
    return (vol_std / vol_mean).where(vol_mean > 0, np.nan)


# ── Cat 61: 模倣急増の検出（バブル動態）──


def h_61_01(df):
    """バブル動態検出: 出来高急増 + 価格上昇 + Vol上昇の同時発生。"""
    vol_spike = _volume_ratio(df['Volume'], 20) > 2.0
    price_up = _n_day_return(df['Close'], 5) > 5.0
    vol_up = _realized_vol(df['Close'].pct_change(), 10) > _realized_vol(df['Close'].pct_change(), 20)
    return vol_spike & price_up & vol_up


def h_61_02(df):
    """模倣急増スコア: 出来高比率×リターン×Vol変化の合成。"""
    vol_r = _volume_ratio(df['Volume'], 20)
    ret_5 = _n_day_return(df['Close'], 5)
    rv_ratio = _realized_vol(df['Close'].pct_change(), 10) / _realized_vol(df['Close'].pct_change(), 20)
    return vol_r * ret_5.clip(lower=0) * rv_ratio


# ── Cat 62: カウンター戦略 ──


def h_62_01(df):
    """急落カウンター: 日次-5%超の翌日にロング。direction_fixed=long。"""
    return _n_day_return(df['Close'], 1).shift(1) < -5.0


def h_62_02(df):
    """急落カウンター: 日次-3%超の翌日にロング。direction_fixed=long。"""
    return _n_day_return(df['Close'], 1).shift(1) < -3.0


# ── Cat 64: 空売り圧力の代理検出 ──


def h_64_01(df):
    """Bear/Bull出来高比率の急変。pair_Volume=Bear出来高。"""
    if 'pair_Volume' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    ratio = df['pair_Volume'] / df['Volume']
    return ratio.where(df['Volume'] > 0, np.nan)


def h_64_02(df):
    """Bear/Bull出来高比率の極端値: 20日間での位置 (0-1)。"""
    ratio = h_64_01(df)
    low_20 = ratio.rolling(20).min()
    high_20 = ratio.rolling(20).max()
    rng = high_20 - low_20
    return ((ratio - low_20) / rng).where(rng > 0, 0.5)


# ── Cat 65: 再帰的フィードバック加速度 ──


def h_65_01(df):
    """下落加速度: 2日目|下落| > 1日目|下落|。direction_fixed=long(減速で反転)。"""
    ret = _n_day_return(df['Close'], 1)
    neg_ret = ret.where(ret < 0, 0).abs()
    return neg_ret - neg_ret.shift(1)  # 正=加速、負=減速


def h_65_02(df):
    """フィードバック減速検出: 3日連続下落中に|下落|が縮小。"""
    ret = _n_day_return(df['Close'], 1)
    consec_down = _consecutive_direction(df['Close'].pct_change()) <= -3
    decelerating = ret.abs() < ret.abs().shift(1)
    return consec_down & decelerating


# ── Cat 68: 平均取引サイズ(v/n)パターン ──
# 5分足専用 (NumTrades列必要)


def h_68_01(df):
    """平均取引サイズ: Volume / NumTrades。"""
    if 'NumTrades' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return _avg_trade_size(df['Volume'], df['NumTrades'])


def h_68_02(df):
    """平均取引サイズの時間帯比率: 同時間帯平均との比。"""
    if 'NumTrades' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    ats = _avg_trade_size(df['Volume'], df['NumTrades'])
    time_avg = ats.groupby(df.index.time).transform('mean')
    return (ats / time_avg).where(time_avg > 0, np.nan)


def h_68_03(df):
    """平均取引サイズの急変: 前バーとの比率。大きい=大口参入。"""
    if 'NumTrades' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    ats = _avg_trade_size(df['Volume'], df['NumTrades'])
    return (ats / ats.shift(1)).where(ats.shift(1) > 0, np.nan)


# ── Cat 69: 取引回数スパイクと出来高スパイクの乖離 ──


def h_69_01(df):
    """VN乖離: 出来高スパイク - 取引回数スパイクの差。"""
    if 'NumTrades' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return _vn_divergence(df['Volume'], df['NumTrades'], 20)


def h_69_02(df):
    """大口参入シグナル: Volume急増 + NumTrades一定（VN乖離が正）。"""
    if 'NumTrades' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    vn = _vn_divergence(df['Volume'], df['NumTrades'], 20)
    return vn > 1.0  # 出来高比率が取引回数比率より1以上大きい


def h_69_03(df):
    """小口パニックシグナル: NumTrades急増 + Volume一定（VN乖離が負）。"""
    if 'NumTrades' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    vn = _vn_divergence(df['Volume'], df['NumTrades'], 20)
    return vn < -1.0


# ── Cat 70: バー内VWAP乖離 ──


def h_70_01(df):
    """バー内VWAP乖離: Close - VWAP。正=買い圧力。5分足専用。"""
    if 'VWAP' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return _bar_vwap_deviation(df['Close'], df['VWAP'])


def h_70_02(df):
    """バー内VWAP乖離の連続: 正が3本以上連続。"""
    if 'VWAP' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    positive = _bar_vwap_deviation(df['Close'], df['VWAP']) > 0
    groups = (positive != positive.shift()).cumsum()
    counts = positive.groupby(groups).cumcount() + 1
    return counts.where(positive, 0)


def h_70_03(df):
    """バー内VWAP乖離率 (%)。5分足専用。"""
    if 'VWAP' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return _vwap_deviation_pct(df['Close'], df['VWAP'])


# ── Cat 71: プレマーケット出来高水準 ──
# 5分足専用。プレマーケット(4:00-9:30 ET)のデータが必要


def h_71_01(df):
    """プレマーケット出来高比率: プレマーケット出来高 / レギュラー平均出来高。"""
    if 'VWAP' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    import datetime
    pre_market = df.index.time < datetime.time(9, 30)
    regular = ~pre_market
    dates = pd.Series(df.index.date, index=df.index)
    pre_vol = df['Volume'].where(pre_market).groupby(dates).transform('sum')
    reg_avg = df['Volume'].where(regular).groupby(dates).transform('mean')
    return (pre_vol / reg_avg).where(reg_avg > 0, np.nan)


def h_71_02(df):
    """プレマーケット取引回数比率。"""
    if 'NumTrades' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    import datetime
    pre_market = df.index.time < datetime.time(9, 30)
    regular = ~pre_market
    dates = pd.Series(df.index.date, index=df.index)
    pre_n = df['NumTrades'].where(pre_market).groupby(dates).transform('sum')
    reg_avg_n = df['NumTrades'].where(regular).groupby(dates).transform('mean')
    return (pre_n / reg_avg_n).where(reg_avg_n > 0, np.nan)


def h_71_03(df):
    """プレマーケットVN乖離: プレマーケットの大口/小口検出。"""
    if 'NumTrades' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    import datetime
    pre_market = df.index.time < datetime.time(9, 30)
    pre_vol_r = _volume_ratio(df['Volume'], 20).where(pre_market, np.nan)
    pre_n_r = _volume_ratio(df['NumTrades'], 20).where(pre_market, np.nan)
    return pre_vol_r - pre_n_r


# ── Cat 72: アフターマーケット→翌朝乖離 ──
# 5分足専用。アフター(16:00-20:00 ET)のデータが必要


def h_72_01(df):
    """アフターマーケット最終値 → 翌朝オープンの乖離率 (%)。"""
    if 'VWAP' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    import datetime
    after_hours = df.index.time >= datetime.time(16, 0)
    dates = pd.Series(df.index.date, index=df.index)
    after_last = df['Close'].where(after_hours).groupby(dates).transform('last')
    # 翌日のオープンとの乖離
    next_day_open = df.groupby(dates)['Open'].transform('first')
    gap = (next_day_open - after_last.shift(1)) / after_last.shift(1) * 100
    return gap


def h_72_02(df):
    """アフターマーケット出来高水準: 高ければ翌日ボラティリティ予測。"""
    if 'VWAP' not in df.columns:
        return pd.Series(np.nan, index=df.index)
    import datetime
    after_hours = df.index.time >= datetime.time(16, 0)
    dates = pd.Series(df.index.date, index=df.index)
    after_vol = df['Volume'].where(after_hours).groupby(dates).transform('sum')
    reg_vol = df['Volume'].where(~after_hours).groupby(dates).transform('sum')
    return (after_vol / reg_vol).where(reg_vol > 0, np.nan)


# ══════════════════════════════════════════════════════════════════════
# HYPOTHESES リスト（Pre-Analysis Plan）
# ══════════════════════════════════════════════════════════════════════

HYPOTHESES: list[dict] = [
    {"id": "H-01-01", "func": h_01_01, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-01-S", "func": h_01_01, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-02", "func": h_01_02, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-02-S", "func": h_01_02, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03a", "func": h_01_03a, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03a-S", "func": h_01_03a, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03b", "func": h_01_03b, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03b-S", "func": h_01_03b, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03c", "func": h_01_03c, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03c-S", "func": h_01_03c, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03d", "func": h_01_03d, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03d-S", "func": h_01_03d, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03e", "func": h_01_03e, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03e-S", "func": h_01_03e, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03f", "func": h_01_03f, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03f-S", "func": h_01_03f, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03g", "func": h_01_03g, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03g-S", "func": h_01_03g, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03h", "func": h_01_03h, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-03h-S", "func": h_01_03h, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-04a", "func": h_01_04a, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-04a-S", "func": h_01_04a, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-04b", "func": h_01_04b, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-04b-S", "func": h_01_04b, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-04c", "func": h_01_04c, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-04c-S", "func": h_01_04c, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-04d", "func": h_01_04d, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-04d-S", "func": h_01_04d, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-05a", "func": h_01_05a, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-05a-S", "func": h_01_05a, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-05b", "func": h_01_05b, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-05b-S", "func": h_01_05b, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-06", "func": h_01_06, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-06-S", "func": h_01_06, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-07", "func": h_01_07, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-07-S", "func": h_01_07, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-08", "func": h_01_08, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-08-S", "func": h_01_08, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-09", "func": h_01_09, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-09-S", "func": h_01_09, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-10", "func": h_01_10, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-01-10-S", "func": h_01_10, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 1},
    {"id": "H-02-01a", "func": h_02_01a, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 2},
    {"id": "H-02-01a-S", "func": h_02_01a, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 2},
    {"id": "H-02-01b", "func": h_02_01b, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 2},
    {"id": "H-02-01b-S", "func": h_02_01b, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 2},
    {"id": "H-02-01c", "func": h_02_01c, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 2},
    {"id": "H-02-01c-S", "func": h_02_01c, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 2},
    {"id": "H-02-02", "func": h_02_02, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 2},
    {"id": "H-02-02-S", "func": h_02_02, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 2},
    {"id": "H-02-03", "func": h_02_03, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 2},
    {"id": "H-02-03-S", "func": h_02_03, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 2},
    {"id": "H-02-04", "func": h_02_04, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 2},
    {"id": "H-02-04-S", "func": h_02_04, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 2},
    {"id": "H-02-05", "func": h_02_05, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": ['VIX', 'VIX3M'], "requires_pair": False, "category": 2},
    {"id": "H-02-05-S", "func": h_02_05, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": ['VIX', 'VIX3M'], "requires_pair": False, "category": 2},
    {"id": "H-03-01", "func": h_03_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 3},
    {"id": "H-03-01-S", "func": h_03_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 3},
    {"id": "H-03-02", "func": h_03_02, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 3},
    {"id": "H-03-02-S", "func": h_03_02, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 3},
    {"id": "H-03-03", "func": h_03_03, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX', 'VIX3M'], "requires_pair": False, "category": 3},
    {"id": "H-03-03-S", "func": h_03_03, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX', 'VIX3M'], "requires_pair": False, "category": 3},
    {"id": "H-03-04", "func": h_03_04, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX', 'VIX3M'], "requires_pair": False, "category": 3},
    {"id": "H-03-04-S", "func": h_03_04, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX', 'VIX3M'], "requires_pair": False, "category": 3},
    {"id": "H-03-05", "func": h_03_05, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 3},
    {"id": "H-03-05-S", "func": h_03_05, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 3},
    {"id": "H-03-06", "func": h_03_06, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 3},
    {"id": "H-03-06-S", "func": h_03_06, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 3},
    {"id": "H-03-07", "func": h_03_07, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 3},
    {"id": "H-03-07-S", "func": h_03_07, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 3},
    {"id": "H-08-01", "func": h_08_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX', 'VIX3M'], "requires_pair": False, "category": 8},
    {"id": "H-08-01-S", "func": h_08_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX', 'VIX3M'], "requires_pair": False, "category": 8},
    {"id": "H-08-02", "func": h_08_02, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": True, "category": 8},
    {"id": "H-08-02-S", "func": h_08_02, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": True, "category": 8},
    {"id": "H-08-03", "func": h_08_03, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX'], "requires_pair": True, "category": 8},
    {"id": "H-08-03-S", "func": h_08_03, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX'], "requires_pair": True, "category": 8},
    {"id": "H-04-01a", "func": h_04_01a, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['BRENT'], "requires_pair": False, "category": 4},
    {"id": "H-04-01a-S", "func": h_04_01a, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['BRENT'], "requires_pair": False, "category": 4},
    {"id": "H-04-01b", "func": h_04_01b, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['BRENT'], "requires_pair": False, "category": 4},
    {"id": "H-04-01b-S", "func": h_04_01b, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['BRENT'], "requires_pair": False, "category": 4},
    {"id": "H-04-02a", "func": h_04_02a, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['HY_SPREAD'], "requires_pair": False, "category": 4},
    {"id": "H-04-02a-S", "func": h_04_02a, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['HY_SPREAD'], "requires_pair": False, "category": 4},
    {"id": "H-04-02b", "func": h_04_02b, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['HY_SPREAD'], "requires_pair": False, "category": 4},
    {"id": "H-04-02b-S", "func": h_04_02b, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['HY_SPREAD'], "requires_pair": False, "category": 4},
    {"id": "H-04-03a", "func": h_04_03a, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['YIELD_CURVE'], "requires_pair": False, "category": 4},
    {"id": "H-04-03a-S", "func": h_04_03a, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['YIELD_CURVE'], "requires_pair": False, "category": 4},
    {"id": "H-04-03b", "func": h_04_03b, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['YIELD_CURVE'], "requires_pair": False, "category": 4},
    {"id": "H-04-03b-S", "func": h_04_03b, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['YIELD_CURVE'], "requires_pair": False, "category": 4},
    {"id": "H-04-04a", "func": h_04_04a, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['USD_INDEX'], "requires_pair": False, "category": 4},
    {"id": "H-04-04a-S", "func": h_04_04a, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['USD_INDEX'], "requires_pair": False, "category": 4},
    {"id": "H-04-04b", "func": h_04_04b, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['USD_INDEX'], "requires_pair": False, "category": 4},
    {"id": "H-04-04b-S", "func": h_04_04b, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['USD_INDEX'], "requires_pair": False, "category": 4},
    {"id": "H-04-05a", "func": h_04_05a, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['US10Y'], "requires_pair": False, "category": 4},
    {"id": "H-04-05a-S", "func": h_04_05a, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['US10Y'], "requires_pair": False, "category": 4},
    {"id": "H-04-05b", "func": h_04_05b, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['US10Y'], "requires_pair": False, "category": 4},
    {"id": "H-04-05b-S", "func": h_04_05b, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['US10Y'], "requires_pair": False, "category": 4},
    {"id": "H-05-01", "func": h_05_01, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 5},
    {"id": "H-05-01-S", "func": h_05_01, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 5},
    {"id": "H-05-02", "func": h_05_02, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 5},
    {"id": "H-05-02-S", "func": h_05_02, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 5},
    {"id": "H-05-03", "func": h_05_03, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 5},
    {"id": "H-05-03-S", "func": h_05_03, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 5},
    {"id": "H-05-04", "func": h_05_04, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 5},
    {"id": "H-05-04-S", "func": h_05_04, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 5},
    {"id": "H-05-05", "func": h_05_05, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 5},
    {"id": "H-05-05-S", "func": h_05_05, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 5},
    {"id": "H-09-01", "func": h_09_01, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 9},
    {"id": "H-09-01-S", "func": h_09_01, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 9},
    {"id": "H-09-02", "func": h_09_02, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 9},
    {"id": "H-09-02-S", "func": h_09_02, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 9},
    {"id": "H-09-03", "func": h_09_03, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 9},
    {"id": "H-09-03-S", "func": h_09_03, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 9},
    {"id": "H-11-01", "func": h_11_01, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": True, "category": 11},
    {"id": "H-11-01-S", "func": h_11_01, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": True, "category": 11},
    {"id": "H-11-02", "func": h_11_02, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": True, "category": 11},
    {"id": "H-11-02-S", "func": h_11_02, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": True, "category": 11},
    {"id": "H-11-03", "func": h_11_03, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": True, "category": 11},
    {"id": "H-11-03-S", "func": h_11_03, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": True, "category": 11},
    {"id": "H-12-01", "func": h_12_01, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 12},
    {"id": "H-12-01-S", "func": h_12_01, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 12},
    {"id": "H-12-02", "func": h_12_02, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 12},
    {"id": "H-12-02-S", "func": h_12_02, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 12},
    {"id": "H-12-03", "func": h_12_03, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 12},
    {"id": "H-12-03-S", "func": h_12_03, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 12},
    {"id": "H-13-01", "func": h_13_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 13},
    {"id": "H-13-01-S", "func": h_13_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 13},
    {"id": "H-13-02", "func": h_13_02, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 13},
    {"id": "H-13-02-S", "func": h_13_02, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 13},
    {"id": "H-13-03", "func": h_13_03, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 13},
    {"id": "H-13-03-S", "func": h_13_03, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 13},
    {"id": "H-14-01", "func": h_14_01, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 14},
    {"id": "H-14-01-S", "func": h_14_01, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 14},
    {"id": "H-14-02", "func": h_14_02, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 14},
    {"id": "H-14-02-S", "func": h_14_02, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 14},
    {"id": "H-14-03", "func": h_14_03, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 14},
    {"id": "H-14-03-S", "func": h_14_03, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 14},
    {"id": "H-17-01a", "func": h_17_01a, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['BRENT'], "requires_pair": False, "category": 17},
    {"id": "H-17-01a-S", "func": h_17_01a, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['BRENT'], "requires_pair": False, "category": 17},
    {"id": "H-17-01b", "func": h_17_01b, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['BRENT'], "requires_pair": False, "category": 17},
    {"id": "H-17-01b-S", "func": h_17_01b, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['BRENT'], "requires_pair": False, "category": 17},
    {"id": "H-17-02a", "func": h_17_02a, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 17},
    {"id": "H-17-02a-S", "func": h_17_02a, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 17},
    {"id": "H-17-02b", "func": h_17_02b, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['HY_SPREAD'], "requires_pair": False, "category": 17},
    {"id": "H-17-02b-S", "func": h_17_02b, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['HY_SPREAD'], "requires_pair": False, "category": 17},
    {"id": "H-18-01", "func": h_18_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 18},
    {"id": "H-18-01-S", "func": h_18_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 18},
    {"id": "H-18-02", "func": h_18_02, "direction": "long", "timeframe": "daily", "bias_test_type": "regime_conditional", "requires_macro": [], "requires_pair": False, "category": 18},
    {"id": "H-18-02-S", "func": h_18_02, "direction": "short", "timeframe": "daily", "bias_test_type": "regime_conditional", "requires_macro": [], "requires_pair": False, "category": 18},
    {"id": "H-18-03", "func": h_18_03, "direction": "long", "timeframe": "daily", "bias_test_type": "regime_conditional", "requires_macro": [], "requires_pair": False, "category": 18},
    {"id": "H-18-03-S", "func": h_18_03, "direction": "short", "timeframe": "daily", "bias_test_type": "regime_conditional", "requires_macro": [], "requires_pair": False, "category": 18},
    {"id": "H-18-04", "func": h_18_04, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 18},
    {"id": "H-18-04-S", "func": h_18_04, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 18},
    {"id": "H-06-01", "func": h_06_01, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 6},
    {"id": "H-06-01-S", "func": h_06_01, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 6},
    {"id": "H-06-02", "func": h_06_02, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 6},
    {"id": "H-06-02-S", "func": h_06_02, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 6},
    {"id": "H-06-03", "func": h_06_03, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 6},
    {"id": "H-06-03-S", "func": h_06_03, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 6},
    {"id": "H-06-04", "func": h_06_04, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 6},
    {"id": "H-06-04-S", "func": h_06_04, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 6},
    {"id": "H-07-01", "func": h_07_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 7},
    {"id": "H-07-01-S", "func": h_07_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 7},
    {"id": "H-07-02", "func": h_07_02, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 7},
    {"id": "H-07-02-S", "func": h_07_02, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 7},
    {"id": "H-07-03", "func": h_07_03, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'VIX3M'], "requires_pair": False, "category": 7},
    {"id": "H-07-03-S", "func": h_07_03, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'VIX3M'], "requires_pair": False, "category": 7},
    {"id": "H-07-04", "func": h_07_04, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 7},
    {"id": "H-07-04-S", "func": h_07_04, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 7},
    {"id": "H-07-05", "func": h_07_05, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'BRENT', 'HY_SPREAD'], "requires_pair": False, "category": 7},
    {"id": "H-07-05-S", "func": h_07_05, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'BRENT', 'HY_SPREAD'], "requires_pair": False, "category": 7},
    {"id": "H-19-01", "func": h_19_01, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 19},
    {"id": "H-19-01-S", "func": h_19_01, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 19},
    {"id": "H-19-02", "func": h_19_02, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 19},
    {"id": "H-19-02-S", "func": h_19_02, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 19},
    {"id": "H-20-01", "func": h_20_01, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 20},
    {"id": "H-20-01-S", "func": h_20_01, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 20},
    {"id": "H-20-02", "func": h_20_02, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 20},
    {"id": "H-20-02-S", "func": h_20_02, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 20},
    {"id": "H-20-03", "func": h_20_03, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 20},
    {"id": "H-20-03-S", "func": h_20_03, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 20},
    {"id": "H-23-01", "func": h_23_01, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 23},
    {"id": "H-23-01-S", "func": h_23_01, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 23},
    {"id": "H-23-02", "func": h_23_02, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 23},
    {"id": "H-23-02-S", "func": h_23_02, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 23},
    {"id": "H-24-01", "func": h_24_01, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 24},
    {"id": "H-24-01-S", "func": h_24_01, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 24},
    {"id": "H-24-02", "func": h_24_02, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 24},
    {"id": "H-24-02-S", "func": h_24_02, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 24},
    {"id": "H-25-01", "func": h_25_01, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 25},
    {"id": "H-25-01-S", "func": h_25_01, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 25},
    {"id": "H-25-02", "func": h_25_02, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 25},
    {"id": "H-25-02-S", "func": h_25_02, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 25},
    {"id": "H-26-01", "func": h_26_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 26},
    {"id": "H-26-01-S", "func": h_26_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "unconditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 26},
    {"id": "H-26-02", "func": h_26_02, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 26},
    {"id": "H-26-02-S", "func": h_26_02, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 26},
    {"id": "H-26-03", "func": h_26_03, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 26},
    {"id": "H-26-03-S", "func": h_26_03, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 26},
    {"id": "H-27-01", "func": h_27_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 27},
    {"id": "H-27-01-S", "func": h_27_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 27},
    {"id": "H-27-02", "func": h_27_02, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 27},
    {"id": "H-27-02-S", "func": h_27_02, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 27},
    {"id": "H-27-03", "func": h_27_03, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 27},
    {"id": "H-27-03-S", "func": h_27_03, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 27},
    {"id": "H-28-01", "func": h_28_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'HY_SPREAD'], "requires_pair": False, "category": 28},
    {"id": "H-28-01-S", "func": h_28_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'HY_SPREAD'], "requires_pair": False, "category": 28},
    {"id": "H-28-02", "func": h_28_02, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'HY_SPREAD', 'YIELD_CURVE'], "requires_pair": False, "category": 28},
    {"id": "H-28-02-S", "func": h_28_02, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'HY_SPREAD', 'YIELD_CURVE'], "requires_pair": False, "category": 28},
    {"id": "H-29-01", "func": h_29_01, "direction": "long", "timeframe": "daily", "bias_test_type": "direction_fixed", "requires_macro": [], "requires_pair": False, "category": 29},
    {"id": "H-29-02", "func": h_29_02, "direction": "long", "timeframe": "daily", "bias_test_type": "direction_fixed", "requires_macro": [], "requires_pair": False, "category": 29},
    {"id": "H-30-01", "func": h_30_01, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 30},
    {"id": "H-30-01-S", "func": h_30_01, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 30},
    {"id": "H-30-02", "func": h_30_02, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 30},
    {"id": "H-30-02-S", "func": h_30_02, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 30},
    {"id": "H-30-03", "func": h_30_03, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 30},
    {"id": "H-30-03-S", "func": h_30_03, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 30},
    {"id": "H-32-01", "func": h_32_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 32},
    {"id": "H-32-01-S", "func": h_32_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 32},
    {"id": "H-32-02", "func": h_32_02, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 32},
    {"id": "H-32-02-S", "func": h_32_02, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 32},
    {"id": "H-32-03", "func": h_32_03, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 32},
    {"id": "H-32-03-S", "func": h_32_03, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 32},
    {"id": "H-32-04", "func": h_32_04, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 32},
    {"id": "H-32-04-S", "func": h_32_04, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 32},
    {"id": "H-32-05", "func": h_32_05, "direction": "long", "timeframe": "daily", "bias_test_type": "regime_conditional", "requires_macro": [], "requires_pair": False, "category": 32},
    {"id": "H-32-05-S", "func": h_32_05, "direction": "short", "timeframe": "daily", "bias_test_type": "regime_conditional", "requires_macro": [], "requires_pair": False, "category": 32},
    {"id": "H-33-01", "func": h_33_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "structural", "requires_macro": ['VIX'], "requires_pair": False, "category": 33},
    {"id": "H-33-01-S", "func": h_33_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "structural", "requires_macro": ['VIX'], "requires_pair": False, "category": 33},
    {"id": "H-33-02", "func": h_33_02, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 33},
    {"id": "H-33-02-S", "func": h_33_02, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 33},
    {"id": "H-33-03", "func": h_33_03, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 33},
    {"id": "H-33-03-S", "func": h_33_03, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 33},
    {"id": "H-34-01", "func": h_34_01, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 34},
    {"id": "H-34-01-S", "func": h_34_01, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 34},
    {"id": "H-34-02", "func": h_34_02, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 34},
    {"id": "H-34-02-S", "func": h_34_02, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": True, "category": 34},
    {"id": "H-35-01", "func": h_35_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 35},
    {"id": "H-35-01-S", "func": h_35_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 35},
    {"id": "H-35-02", "func": h_35_02, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 35},
    {"id": "H-35-02-S", "func": h_35_02, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 35},
    {"id": "H-35-03", "func": h_35_03, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['HY_SPREAD'], "requires_pair": False, "category": 35},
    {"id": "H-35-03-S", "func": h_35_03, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['HY_SPREAD'], "requires_pair": False, "category": 35},
    {"id": "H-37-01", "func": h_37_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "direction_fixed", "requires_macro": ['VIX'], "requires_pair": False, "category": 37},
    {"id": "H-37-02", "func": h_37_02, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "direction_fixed", "requires_macro": ['VIX'], "requires_pair": False, "category": 37},
    {"id": "H-40-01", "func": h_40_01, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 40},
    {"id": "H-40-01-S", "func": h_40_01, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 40},
    {"id": "H-40-02", "func": h_40_02, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 40},
    {"id": "H-40-02-S", "func": h_40_02, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 40},
    {"id": "H-41-01", "func": h_41_01, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 41},
    {"id": "H-41-01-S", "func": h_41_01, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 41},
    {"id": "H-41-02", "func": h_41_02, "direction": "long", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 41},
    {"id": "H-41-02-S", "func": h_41_02, "direction": "short", "timeframe": "daily", "bias_test_type": "structural", "requires_macro": [], "requires_pair": False, "category": 41},
    {"id": "H-42-01", "func": h_42_01, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 42},
    {"id": "H-42-01-S", "func": h_42_01, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 42},
    {"id": "H-42-02", "func": h_42_02, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 42},
    {"id": "H-42-02-S", "func": h_42_02, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 42},
    {"id": "H-43-01", "func": h_43_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'BRENT', 'HY_SPREAD', 'YIELD_CURVE', 'US10Y'], "requires_pair": False, "category": 43},
    {"id": "H-43-01-S", "func": h_43_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'BRENT', 'HY_SPREAD', 'YIELD_CURVE', 'US10Y'], "requires_pair": False, "category": 43},
    {"id": "H-43-02", "func": h_43_02, "direction": "long", "timeframe": "daily", "bias_test_type": "regime_conditional", "requires_macro": [], "requires_pair": False, "category": 43},
    {"id": "H-43-02-S", "func": h_43_02, "direction": "short", "timeframe": "daily", "bias_test_type": "regime_conditional", "requires_macro": [], "requires_pair": False, "category": 43},
    {"id": "H-44-01", "func": h_44_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'HY_SPREAD'], "requires_pair": False, "category": 44},
    {"id": "H-44-01-S", "func": h_44_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'HY_SPREAD'], "requires_pair": False, "category": 44},
    {"id": "H-44-02", "func": h_44_02, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'HY_SPREAD'], "requires_pair": False, "category": 44},
    {"id": "H-44-02-S", "func": h_44_02, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX', 'HY_SPREAD'], "requires_pair": False, "category": 44},
    {"id": "H-46-01", "func": h_46_01, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": True, "category": 46},
    {"id": "H-46-01-S", "func": h_46_01, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": True, "category": 46},
    {"id": "H-46-02", "func": h_46_02, "direction": "long", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 46},
    {"id": "H-46-02-S", "func": h_46_02, "direction": "short", "timeframe": "daily", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 46},
    {"id": "H-50-01", "func": h_50_01, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 50},
    {"id": "H-50-01-S", "func": h_50_01, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 50},
    {"id": "H-50-02", "func": h_50_02, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 50},
    {"id": "H-50-02-S", "func": h_50_02, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 50},
    {"id": "H-50-03", "func": h_50_03, "direction": "long", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 50},
    {"id": "H-50-03-S", "func": h_50_03, "direction": "short", "timeframe": "daily_macro", "bias_test_type": "regime_conditional", "requires_macro": ['VIX'], "requires_pair": False, "category": 50},
    {"id": "H-53-01", "func": h_53_01, "direction": "long", "timeframe": "daily", "bias_test_type": "regime_conditional", "requires_macro": [], "requires_pair": False, "category": 53},
    {"id": "H-53-01-S", "func": h_53_01, "direction": "short", "timeframe": "daily", "bias_test_type": "regime_conditional", "requires_macro": [], "requires_pair": False, "category": 53},
    {"id": "H-53-02", "func": h_53_02, "direction": "long", "timeframe": "daily", "bias_test_type": "regime_conditional", "requires_macro": [], "requires_pair": False, "category": 53},
    {"id": "H-53-02-S", "func": h_53_02, "direction": "short", "timeframe": "daily", "bias_test_type": "regime_conditional", "requires_macro": [], "requires_pair": False, "category": 53},
    {"id": "H-61-01-S", "func": h_61_01, "direction": "short", "timeframe": "daily", "bias_test_type": "direction_fixed", "requires_macro": [], "requires_pair": False, "category": 61},
    {"id": "H-61-02-S", "func": h_61_02, "direction": "short", "timeframe": "daily", "bias_test_type": "direction_fixed", "requires_macro": [], "requires_pair": False, "category": 61},
    {"id": "H-62-01", "func": h_62_01, "direction": "long", "timeframe": "daily", "bias_test_type": "direction_fixed", "requires_macro": [], "requires_pair": False, "category": 62},
    {"id": "H-62-02", "func": h_62_02, "direction": "long", "timeframe": "daily", "bias_test_type": "direction_fixed", "requires_macro": [], "requires_pair": False, "category": 62},
    {"id": "H-64-01-S", "func": h_64_01, "direction": "short", "timeframe": "daily", "bias_test_type": "direction_fixed", "requires_macro": [], "requires_pair": True, "category": 64},
    {"id": "H-64-02-S", "func": h_64_02, "direction": "short", "timeframe": "daily", "bias_test_type": "direction_fixed", "requires_macro": [], "requires_pair": False, "category": 64},
    {"id": "H-65-01-S", "func": h_65_01, "direction": "short", "timeframe": "daily", "bias_test_type": "direction_fixed", "requires_macro": [], "requires_pair": False, "category": 65},
    {"id": "H-65-02-S", "func": h_65_02, "direction": "short", "timeframe": "intraday", "bias_test_type": "direction_fixed", "requires_macro": [], "requires_pair": False, "category": 65},
    {"id": "H-68-01", "func": h_68_01, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 68},
    {"id": "H-68-01-S", "func": h_68_01, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 68},
    {"id": "H-68-02", "func": h_68_02, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 68},
    {"id": "H-68-02-S", "func": h_68_02, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 68},
    {"id": "H-68-03", "func": h_68_03, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 68},
    {"id": "H-68-03-S", "func": h_68_03, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 68},
    {"id": "H-69-01", "func": h_69_01, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 69},
    {"id": "H-69-01-S", "func": h_69_01, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 69},
    {"id": "H-69-02", "func": h_69_02, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 69},
    {"id": "H-69-02-S", "func": h_69_02, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 69},
    {"id": "H-69-03", "func": h_69_03, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 69},
    {"id": "H-69-03-S", "func": h_69_03, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 69},
    {"id": "H-70-01", "func": h_70_01, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 70},
    {"id": "H-70-01-S", "func": h_70_01, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 70},
    {"id": "H-70-02", "func": h_70_02, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 70},
    {"id": "H-70-02-S", "func": h_70_02, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 70},
    {"id": "H-70-03", "func": h_70_03, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 70},
    {"id": "H-70-03-S", "func": h_70_03, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 70},
    {"id": "H-71-01", "func": h_71_01, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 71},
    {"id": "H-71-01-S", "func": h_71_01, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 71},
    {"id": "H-71-02", "func": h_71_02, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 71},
    {"id": "H-71-02-S", "func": h_71_02, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 71},
    {"id": "H-71-03", "func": h_71_03, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 71},
    {"id": "H-71-03-S", "func": h_71_03, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 71},
    {"id": "H-72-01", "func": h_72_01, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 72},
    {"id": "H-72-01-S", "func": h_72_01, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 72},
    {"id": "H-72-02", "func": h_72_02, "direction": "long", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 72},
    {"id": "H-72-02-S", "func": h_72_02, "direction": "short", "timeframe": "intraday", "bias_test_type": "unconditional", "requires_macro": [], "requires_pair": False, "category": 72},
]

ROUND2_CANDIDATES: list[dict] = [
    {"category": 16, "sub_signals": 2, "reason": "Stage 1結果依存（50%未満シグナル反転）"},
    {"category": 31, "sub_signals": 3, "reason": "ポジション管理（エントリーシグナルでない）"},
    {"category": 36, "sub_signals": 2, "reason": "Stage 2 Walk-forward結果依存"},
    {"category": 38, "sub_signals": 2, "reason": "ポジション比率管理（エントリーシグナルでない）"},
    {"category": 39, "sub_signals": 4, "reason": "執行最適化（Stage 3）"},
    {"category": 45, "sub_signals": 3, "reason": "Stage 1結果依存（通過シグナルの遅延版）"},
    {"category": 47, "sub_signals": 3, "reason": "DuckDB eventsテーブル依存"},
    {"category": 48, "sub_signals": 2, "reason": "トレード履歴依存（エントリーシグナルでない）"},
    {"category": 49, "sub_signals": 2, "reason": "Round 2探索手法（結果→シグナル逆引き）"},
    {"category": 51, "sub_signals": 1, "reason": "Cat 36依存（シグナル減衰検出後の入替え）"},
    {"category": 52, "sub_signals": 3, "reason": "DuckDB eventsテーブル依存"},
    {"category": 54, "sub_signals": 3, "reason": "Stage 1結果のメタ分析（制約×精度）"},
    {"category": 55, "sub_signals": 2, "reason": "Stage 1結果依存（失敗条件特定）"},
    {"category": 56, "sub_signals": 2, "reason": "Stage 3評価（キャリーコスト）"},
    {"category": 57, "sub_signals": 2, "reason": "Stage 2/3評価指標（Sortino比）"},
    {"category": 58, "sub_signals": 1, "reason": "Stage 3評価（複利効果）"},
    {"category": 59, "sub_signals": 3, "reason": "Stage 1全結果依存（効かない市場状態）"},
    {"category": 60, "sub_signals": 2, "reason": "Stage 3評価（摩擦後期待値）"},
    {"category": 63, "sub_signals": 2, "reason": "Runner設計問題（情報鮮度モード切替）"},
    {"category": 66, "sub_signals": 3, "reason": "出口戦略（エントリーシグナルでない）"},
    {"category": 67, "sub_signals": 2, "reason": "Stage 3評価指標（テールリスク）"},
]
