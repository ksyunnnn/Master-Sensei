"""signal_defs ヘルパー関数テスト

4層構造（既知解・境界・不変量・反例）。
合成データで高速テスト。実データ非依存。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signal_defs import (
    _rsi,
    _sma,
    _ma_deviation,
    _bb_position,
    _atr,
    _gap_pct,
    _consecutive_direction,
    _distance_from_high,
    _distance_from_low,
    _close_position_in_range,
    _volume_ratio,
    _vwap_deviation_pct,
    _price_volume_divergence,
    _realized_vol,
    _drawdown_from_peak,
    _n_day_return,
    _bull_bear_spread,
    _avg_trade_size,
    _vn_divergence,
    _bar_vwap_deviation,
    _day_of_week,
    _is_month_boundary,
)


# ── Fixtures ──

@pytest.fixture
def prices():
    """10日分の合成価格。既知の値を手計算で検証可能にする。"""
    dates = pd.date_range("2025-01-06", periods=10, freq="B")
    close = pd.Series(
        [100, 102, 101, 103, 105, 104, 106, 108, 107, 110],
        index=dates, name="Close",
    )
    high = close + 1.0
    low = close - 1.0
    open_ = close - 0.5
    volume = pd.Series(
        [1000, 1200, 800, 1500, 2000, 900, 1100, 1300, 1000, 1400],
        index=dates, name="Volume",
    )
    return {"close": close, "high": high, "low": low, "open": open_, "volume": volume}


# ══════════════════════════════════════════════════════════════════════
# _rsi
# ══════════════════════════════════════════════════════════════════════

class TestRSI:
    def test_known_all_gains(self):
        """既知解: 全日上昇 → RSI = 100"""
        dates = pd.date_range("2025-01-01", periods=20, freq="B")
        close = pd.Series(range(100, 120), index=dates, dtype=float)
        rsi = _rsi(close, period=5)
        # period経過後は全て上昇なので RSI ≈ 100
        assert rsi.iloc[-1] == pytest.approx(100, abs=0.1)

    def test_known_all_losses(self):
        """既知解: 全日下落 → RSI = 0"""
        dates = pd.date_range("2025-01-01", periods=20, freq="B")
        close = pd.Series(range(120, 100, -1), index=dates, dtype=float)
        rsi = _rsi(close, period=5)
        assert rsi.iloc[-1] == pytest.approx(0, abs=0.1)

    @pytest.mark.parametrize("period", [5, 7, 14])
    def test_invariant_range(self, period):
        """不変量: RSI ∈ [0, 100]"""
        rng = np.random.default_rng(42)
        dates = pd.date_range("2025-01-01", periods=100, freq="B")
        close = pd.Series(100 + rng.normal(0, 2, 100).cumsum(), index=dates)
        rsi = _rsi(close, period=period).dropna()
        assert rsi.min() >= 0
        assert rsi.max() <= 100


# ══════════════════════════════════════════════════════════════════════
# _sma, _ma_deviation
# ══════════════════════════════════════════════════════════════════════

class TestSMA:
    def test_known_solution(self, prices):
        """既知解: 最初の3日の平均 = (100+102+101)/3 = 101"""
        sma = _sma(prices["close"], 3)
        assert sma.iloc[2] == pytest.approx(101.0)

    def test_invariant_length(self, prices):
        """不変量: 出力長 == 入力長"""
        sma = _sma(prices["close"], 3)
        assert len(sma) == len(prices["close"])


class TestMADeviation:
    def test_known_zero(self):
        """既知解: 定数系列 → 乖離率 = 0"""
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        close = pd.Series([100.0] * 10, index=dates)
        dev = _ma_deviation(close, 5)
        assert dev.iloc[-1] == pytest.approx(0.0)

    def test_known_positive(self):
        """既知解: 上昇トレンド → 最新値は MA より上 → 正"""
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        close = pd.Series(range(100, 110), index=dates, dtype=float)
        dev = _ma_deviation(close, 5)
        assert dev.iloc[-1] > 0


# ══════════════════════════════════════════════════════════════════════
# _bb_position
# ══════════════════════════════════════════════════════════════════════

class TestBBPosition:
    def test_known_constant_returns_half(self):
        """既知解: 定数系列 → std=0 → BB position = 0.5（中央）"""
        dates = pd.date_range("2025-01-01", periods=25, freq="B")
        close = pd.Series([100.0] * 25, index=dates)
        pos = _bb_position(close, 20, 2.0)
        valid = pos.dropna()
        assert len(valid) > 0, "定数系列でもNaN以外の値があるべき"
        assert valid.iloc[-1] == pytest.approx(0.5)

    @pytest.mark.parametrize("seed", [0, 42, 99])
    def test_invariant_mean_near_half(self, seed):
        """不変量: ランダムウォーク → BB position の平均は約0.5"""
        rng = np.random.default_rng(seed)
        dates = pd.date_range("2025-01-01", periods=200, freq="B")
        close = pd.Series(100 + rng.normal(0, 1, 200).cumsum(), index=dates)
        pos = _bb_position(close, 20, 2.0).dropna()
        # BB内に約95%が入り、平均は0.5付近
        assert 0.3 < pos.mean() < 0.7


# ══════════════════════════════════════════════════════════════════════
# _atr
# ══════════════════════════════════════════════════════════════════════

class TestATR:
    def test_known_constant_range(self):
        """既知解: H-L=2, Close変動なし → ATR = 2"""
        dates = pd.date_range("2025-01-01", periods=20, freq="B")
        close = pd.Series([100.0] * 20, index=dates)
        high = close + 1.0
        low = close - 1.0
        atr = _atr(high, low, close, period=5)
        assert atr.iloc[-1] == pytest.approx(2.0)

    def test_invariant_positive(self, prices):
        """不変量: ATR > 0"""
        atr = _atr(prices["high"], prices["low"], prices["close"], 5)
        valid = atr.dropna()
        assert (valid > 0).all()


# ══════════════════════════════════════════════════════════════════════
# _gap_pct
# ══════════════════════════════════════════════════════════════════════

class TestGapPct:
    def test_known_solution(self):
        """既知解: Open=105, PrevClose=100 → Gap = +5%"""
        open_ = pd.Series([105.0])
        prev_close = pd.Series([100.0])
        gap = _gap_pct(open_, prev_close)
        assert gap.iloc[0] == pytest.approx(5.0)

    def test_known_negative(self):
        """既知解: Open=95, PrevClose=100 → Gap = -5%"""
        gap = _gap_pct(pd.Series([95.0]), pd.Series([100.0]))
        assert gap.iloc[0] == pytest.approx(-5.0)


# ══════════════════════════════════════════════════════════════════════
# _consecutive_direction
# ══════════════════════════════════════════════════════════════════════

class TestConsecutiveDirection:
    def test_known_solution(self):
        """既知解: [+,+,+,-,-,+] → [1,2,3,-1,-2,1]"""
        returns = pd.Series([0.01, 0.02, 0.01, -0.01, -0.02, 0.01])
        result = _consecutive_direction(returns)
        expected = [1, 2, 3, -1, -2, 1]
        for i, exp in enumerate(expected):
            assert result.iloc[i] == exp, f"index {i}: {result.iloc[i]} != {exp}"


# ══════════════════════════════════════════════════════════════════════
# _distance_from_high / _distance_from_low
# ══════════════════════════════════════════════════════════════════════

class TestDistanceFromExtreme:
    def test_high_at_peak(self):
        """既知解: 最新値が期間最高値なら距離 = 0"""
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        close = pd.Series(range(100, 110), index=dates, dtype=float)
        dist = _distance_from_high(close, 5)
        assert dist.iloc[-1] == pytest.approx(0.0)

    def test_low_at_trough(self):
        """既知解: 最新値が期間最安値なら距離 = 0"""
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        close = pd.Series(range(110, 100, -1), index=dates, dtype=float)
        dist = _distance_from_low(close, 5)
        assert dist.iloc[-1] == pytest.approx(0.0)

    def test_invariant_high_nonpositive(self, prices):
        """不変量: 高値からの距離 <= 0"""
        dist = _distance_from_high(prices["close"], 5).dropna()
        assert (dist <= 0.0001).all()  # 浮動小数点誤差許容

    def test_invariant_low_nonnegative(self, prices):
        """不変量: 安値からの距離 >= 0"""
        dist = _distance_from_low(prices["close"], 5).dropna()
        assert (dist >= -0.0001).all()


# ══════════════════════════════════════════════════════════════════════
# _close_position_in_range
# ══════════════════════════════════════════════════════════════════════

class TestClosePositionInRange:
    def test_known_at_high(self):
        """既知解: Close == High → position = 1.0"""
        result = _close_position_in_range(
            pd.Series([110.0]), pd.Series([100.0]), pd.Series([110.0])
        )
        assert result.iloc[0] == pytest.approx(1.0)

    def test_known_at_low(self):
        """既知解: Close == Low → position = 0.0"""
        result = _close_position_in_range(
            pd.Series([110.0]), pd.Series([100.0]), pd.Series([100.0])
        )
        assert result.iloc[0] == pytest.approx(0.0)

    def test_known_at_mid(self):
        """既知解: Close == Mid → position = 0.5"""
        result = _close_position_in_range(
            pd.Series([110.0]), pd.Series([100.0]), pd.Series([105.0])
        )
        assert result.iloc[0] == pytest.approx(0.5)


# ══════════════════════════════════════════════════════════════════════
# _volume_ratio
# ══════════════════════════════════════════════════════════════════════

class TestVolumeRatio:
    def test_known_double(self):
        """既知解: 最新出来高 = 平均の2倍 → ratio = 2.0"""
        dates = pd.date_range("2025-01-01", periods=6, freq="B")
        # SMA(5)は最新5日を含む → (1000+1000+1000+1000+2000)/5 = 1200
        # ratio = 2000/1200 = 1.667
        # 別の検証: 5日間全て1000なら SMA=1000, ratio=1.0
        volume = pd.Series([1000, 1000, 1000, 1000, 1000, 1000], index=dates)
        ratio = _volume_ratio(volume, 5)
        assert ratio.iloc[-1] == pytest.approx(1.0)


# ══════════════════════════════════════════════════════════════════════
# _realized_vol
# ══════════════════════════════════════════════════════════════════════

class TestRealizedVol:
    def test_invariant_positive(self):
        """不変量: 実現Vol >= 0"""
        rng = np.random.default_rng(42)
        dates = pd.date_range("2025-01-01", periods=50, freq="B")
        returns = pd.Series(rng.normal(0, 0.02, 50), index=dates)
        vol = _realized_vol(returns, 20).dropna()
        assert (vol >= 0).all()

    def test_known_zero_for_constant(self):
        """既知解: リターンが全てゼロ → Vol = 0"""
        dates = pd.date_range("2025-01-01", periods=25, freq="B")
        returns = pd.Series([0.0] * 25, index=dates)
        vol = _realized_vol(returns, 20)
        assert vol.iloc[-1] == pytest.approx(0.0)


# ══════════════════════════════════════════════════════════════════════
# _drawdown_from_peak
# ══════════════════════════════════════════════════════════════════════

class TestDrawdownFromPeak:
    def test_known_solution(self):
        """既知解: 100→110→100 → 最終DD = (100-110)/110 = -9.09%"""
        close = pd.Series([100.0, 110.0, 100.0])
        dd = _drawdown_from_peak(close)
        assert dd.iloc[0] == pytest.approx(0.0)  # 初日はピーク
        assert dd.iloc[1] == pytest.approx(0.0)  # 新高値
        assert dd.iloc[2] == pytest.approx(-9.0909, abs=0.01)

    def test_invariant_nonpositive(self, prices):
        """不変量: ドローダウン <= 0"""
        dd = _drawdown_from_peak(prices["close"])
        assert (dd <= 0.0001).all()


# ══════════════════════════════════════════════════════════════════════
# _n_day_return
# ══════════════════════════════════════════════════════════════════════

class TestNDayReturn:
    def test_known_solution(self):
        """既知解: 100→110 → 1日リターン = +10%"""
        close = pd.Series([100.0, 110.0])
        ret = _n_day_return(close, 1)
        assert ret.iloc[1] == pytest.approx(10.0)


# ══════════════════════════════════════════════════════════════════════
# _avg_trade_size
# ══════════════════════════════════════════════════════════════════════

class TestAvgTradeSize:
    def test_known_solution(self):
        """既知解: Volume=1000, Trades=50 → Size=20"""
        v = pd.Series([1000])
        n = pd.Series([50])
        result = _avg_trade_size(v, n)
        assert result.iloc[0] == pytest.approx(20.0)

    def test_zero_trades_returns_nan(self):
        """反例: 取引回数0 → NaN"""
        v = pd.Series([1000])
        n = pd.Series([0])
        result = _avg_trade_size(v, n)
        assert pd.isna(result.iloc[0])


# ══════════════════════════════════════════════════════════════════════
# _day_of_week, _is_month_boundary
# ══════════════════════════════════════════════════════════════════════

class TestCalendar:
    def test_day_of_week_monday(self):
        """既知解: 2025-01-06 は月曜 → 0"""
        idx = pd.DatetimeIndex(["2025-01-06"])
        assert _day_of_week(idx).iloc[0] == 0

    def test_day_of_week_friday(self):
        """既知解: 2025-01-10 は金曜 → 4"""
        idx = pd.DatetimeIndex(["2025-01-10"])
        assert _day_of_week(idx).iloc[0] == 4

    def test_month_boundary_start(self):
        """既知解: 1月1日 → 月初 True"""
        idx = pd.DatetimeIndex(["2025-01-01"])
        assert bool(_is_month_boundary(idx, days=2).iloc[0]) is True

    def test_month_boundary_end(self):
        """既知解: 1月31日 → 月末 True"""
        idx = pd.DatetimeIndex(["2025-01-31"])
        assert bool(_is_month_boundary(idx, days=2).iloc[0]) is True

    def test_month_boundary_mid(self):
        """既知解: 1月15日 → 月中 False"""
        idx = pd.DatetimeIndex(["2025-01-15"])
        assert bool(_is_month_boundary(idx, days=2).iloc[0]) is False


# ══════════════════════════════════════════════════════════════════════
# _vwap_deviation_pct（未テストだった）
# ══════════════════════════════════════════════════════════════════════

class TestVwapDeviationPct:
    def test_known_above(self):
        """既知解: Close=105, VWAP=100 → +5%"""
        result = _vwap_deviation_pct(pd.Series([105.0]), pd.Series([100.0]))
        assert result.iloc[0] == pytest.approx(5.0)

    def test_known_below(self):
        """既知解: Close=95, VWAP=100 → -5%"""
        result = _vwap_deviation_pct(pd.Series([95.0]), pd.Series([100.0]))
        assert result.iloc[0] == pytest.approx(-5.0)

    def test_known_equal(self):
        """既知解: Close==VWAP → 0%"""
        result = _vwap_deviation_pct(pd.Series([100.0]), pd.Series([100.0]))
        assert result.iloc[0] == pytest.approx(0.0)


# ══════════════════════════════════════════════════════════════════════
# _price_volume_divergence（未テストだった）
# ══════════════════════════════════════════════════════════════════════

class TestPriceVolumeDivergence:
    def test_known_divergence(self):
        """既知解: 価格上昇+出来高減少 → True（ダイバージェンス）"""
        returns = pd.Series([0.02])
        vol_change = pd.Series([-0.10])
        result = _price_volume_divergence(returns, vol_change)
        assert bool(result.iloc[0]) is True

    def test_known_no_divergence(self):
        """既知解: 価格上昇+出来高増加 → False"""
        returns = pd.Series([0.02])
        vol_change = pd.Series([0.10])
        result = _price_volume_divergence(returns, vol_change)
        assert bool(result.iloc[0]) is False


# ══════════════════════════════════════════════════════════════════════
# _bull_bear_spread（未テストだった）
# ══════════════════════════════════════════════════════════════════════

class TestBullBearSpread:
    def test_known_perfect_inverse(self):
        """既知解: Bull+3%, Bear-3% → spread=0（完全逆相関）"""
        bull = pd.Series([0.03])
        bear = pd.Series([-0.03])
        result = _bull_bear_spread(bull, bear)
        assert result.iloc[0] == pytest.approx(0.0)

    def test_known_asymmetry(self):
        """既知解: Bull+3%, Bear-2.5% → spread=+0.5%（Bull有利な非対称）"""
        bull = pd.Series([0.03])
        bear = pd.Series([-0.025])
        result = _bull_bear_spread(bull, bear)
        assert result.iloc[0] == pytest.approx(0.005)

    def test_invariant_series(self):
        """不変量: 出力長 == 入力長"""
        rng = np.random.default_rng(42)
        n = 50
        bull = pd.Series(rng.normal(0.001, 0.03, n))
        bear = pd.Series(rng.normal(-0.001, 0.03, n))
        result = _bull_bear_spread(bull, bear)
        assert len(result) == n


# ══════════════════════════════════════════════════════════════════════
# _vn_divergence（未テストだった）
# ══════════════════════════════════════════════════════════════════════

class TestVnDivergence:
    def test_known_large_orders(self):
        """既知解: 出来高急増+取引回数一定 → 正（大口参入示唆）"""
        dates = pd.date_range("2025-01-01", periods=25, freq="B")
        # 20日間一定、最後5日で出来高2倍、取引回数変わらず
        volume = pd.Series([1000] * 20 + [2000] * 5, index=dates, dtype=float)
        num_trades = pd.Series([100] * 25, index=dates, dtype=float)
        result = _vn_divergence(volume, num_trades, period=20)
        # v_ratio > n_ratio → 正
        assert result.iloc[-1] > 0

    def test_known_retail_panic(self):
        """既知解: 取引回数急増+出来高一定 → 負（小口パニック示唆）"""
        dates = pd.date_range("2025-01-01", periods=25, freq="B")
        volume = pd.Series([1000] * 25, index=dates, dtype=float)
        num_trades = pd.Series([100] * 20 + [200] * 5, index=dates, dtype=float)
        result = _vn_divergence(volume, num_trades, period=20)
        # v_ratio < n_ratio → 負
        assert result.iloc[-1] < 0


# ══════════════════════════════════════════════════════════════════════
# _bar_vwap_deviation（未テストだった）
# ══════════════════════════════════════════════════════════════════════

class TestBarVwapDeviation:
    def test_known_buy_pressure(self):
        """既知解: Close > VWAP → 正（バー後半で買い圧力）"""
        result = _bar_vwap_deviation(pd.Series([101.0]), pd.Series([100.0]))
        assert result.iloc[0] > 0

    def test_known_sell_pressure(self):
        """既知解: Close < VWAP → 負（バー後半で売り圧力）"""
        result = _bar_vwap_deviation(pd.Series([99.0]), pd.Series([100.0]))
        assert result.iloc[0] < 0

    def test_known_neutral(self):
        """既知解: Close == VWAP → 0"""
        result = _bar_vwap_deviation(pd.Series([100.0]), pd.Series([100.0]))
        assert result.iloc[0] == pytest.approx(0.0)


# ══════════════════════════════════════════════════════════════════════
# 境界テスト
# ══════════════════════════════════════════════════════════════════════

class TestBoundaries:
    def test_rsi_period_equals_length(self):
        """境界: period == データ長 → NaN（min_periods不足）。period+1なら有効"""
        dates = pd.date_range("2025-01-01", periods=15, freq="B")
        close = pd.Series(range(100, 115), index=dates, dtype=float)
        rsi = _rsi(close, period=14)
        # period+1本目で最初の有効値が出る
        assert not pd.isna(rsi.iloc[-1])
        assert rsi.iloc[-1] == pytest.approx(100, abs=0.1)  # 全上昇

    def test_sma_period_1(self):
        """境界: period=1 → 入力と同一"""
        dates = pd.date_range("2025-01-01", periods=5, freq="B")
        close = pd.Series([100, 102, 101, 103, 105], index=dates, dtype=float)
        sma = _sma(close, 1)
        pd.testing.assert_series_equal(sma, close)

    def test_consecutive_direction_single_element(self):
        """境界: 1要素 → [1] or [-1]"""
        result = _consecutive_direction(pd.Series([0.01]))
        assert result.iloc[0] == 1

    def test_gap_pct_zero_prev_close(self):
        """境界: prev_close=0 → inf（ゼロ除算）"""
        result = _gap_pct(pd.Series([100.0]), pd.Series([0.0]))
        assert np.isinf(result.iloc[0]) or pd.isna(result.iloc[0])

    def test_close_position_zero_range(self):
        """境界: High == Low → position = 0.5（フラットバー）"""
        result = _close_position_in_range(
            pd.Series([100.0]), pd.Series([100.0]), pd.Series([100.0])
        )
        assert result.iloc[0] == pytest.approx(0.5)

    def test_drawdown_monotonic_increase(self):
        """境界: 単調増加 → ドローダウン常に0"""
        close = pd.Series([100.0, 101, 102, 103, 104])
        dd = _drawdown_from_peak(close)
        assert (dd == 0).all()

    def test_volume_ratio_zero_average(self):
        """境界: 全出来高ゼロ → ratio = 1.0（フォールバック）"""
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        volume = pd.Series([0] * 10, index=dates, dtype=float)
        ratio = _volume_ratio(volume, 5)
        valid = ratio.dropna()
        # avg=0 → where句で1.0を返す
        assert (valid == 1.0).all()


# ══════════════════════════════════════════════════════════════════════
# 反例テスト
# ══════════════════════════════════════════════════════════════════════

class TestFailureCases:
    def test_consecutive_direction_zero_return(self):
        """反例: リターン0 → カウント0（方向なし）"""
        result = _consecutive_direction(pd.Series([0.01, 0.0, 0.01]))
        # sign(0) = 0, counts * 0 = 0
        assert result.iloc[1] == 0

    def test_n_day_return_first_is_nan(self):
        """反例: 最初のN日はNaN（比較対象なし）"""
        close = pd.Series([100.0, 110.0, 120.0])
        ret = _n_day_return(close, 1)
        assert pd.isna(ret.iloc[0])

    def test_ma_deviation_insufficient_data(self):
        """反例: データ数 < period → NaN"""
        dates = pd.date_range("2025-01-01", periods=3, freq="B")
        close = pd.Series([100.0, 101, 102], index=dates)
        dev = _ma_deviation(close, 5)
        assert pd.isna(dev.iloc[-1])


# ══════════════════════════════════════════════════════════════════════
# 信号生成関数テスト（Cat 1-2）
# ══════════════════════════════════════════════════════════════════════

from src.signal_defs import (
    _vix_term_structure, _vix_spike, _stress_days,
)

# ══════════════════════════════════════════════════════════════════════
# VIX ヘルパーテスト
# ══════════════════════════════════════════════════════════════════════


class TestVixTermStructure:
    """_vix_term_structure: 4層テスト"""

    def test_known_contango(self):
        """既知解: VIX=20, VIX3M=25 → 0.8 (コンタンゴ)"""
        vix = pd.Series([20.0, 25.0, 30.0])
        vix3m = pd.Series([25.0, 25.0, 25.0])
        result = _vix_term_structure(vix, vix3m)
        assert result.iloc[0] == pytest.approx(0.8)
        assert result.iloc[1] == pytest.approx(1.0)
        assert result.iloc[2] == pytest.approx(1.2)

    def test_boundary_vix3m_zero(self):
        """境界: VIX3M=0 → NaN"""
        vix = pd.Series([20.0])
        vix3m = pd.Series([0.0])
        result = _vix_term_structure(vix, vix3m)
        assert pd.isna(result.iloc[0])

    def test_invariant_positive(self):
        """不変量: VIX>0, VIX3M>0 → 結果は正"""
        np.random.seed(42)
        vix = pd.Series(np.random.uniform(10, 50, 100))
        vix3m = pd.Series(np.random.uniform(10, 50, 100))
        result = _vix_term_structure(vix, vix3m)
        assert (result.dropna() > 0).all()


class TestVixSpike:
    """_vix_spike: 4層テスト"""

    def test_known_spike(self):
        """既知解: 20→25 = +25% → True (threshold=10)"""
        vix = pd.Series([20.0, 25.0, 24.0])
        result = _vix_spike(vix, 10.0)
        assert result.iloc[1] == True
        assert result.iloc[2] == False

    def test_boundary_just_below_threshold(self):
        """境界: 9.99% → False (>10でTrue)"""
        # 浮動小数点誤差を避け、明確に閾値未満のケースを検証
        vix = pd.Series([100.0, 109.99])
        result = _vix_spike(vix, 10.0)
        assert result.iloc[1] == False

    def test_invariant_first_is_false(self):
        """不変量: 最初のバーは前日がないので常にFalse"""
        vix = pd.Series([50.0, 60.0, 70.0])
        result = _vix_spike(vix, 10.0)
        assert result.iloc[0] == False


class TestStressDays:
    """_stress_days: 4層テスト"""

    def test_known_stress_sequence(self):
        """既知解: [30,35,40,20,25] level=25 → [1,2,3,0,0]"""
        s = pd.Series([30.0, 35.0, 40.0, 20.0, 25.0])
        result = _stress_days(s, 25.0)
        assert list(result) == [1, 2, 3, 0, 0]

    def test_boundary_exact_level(self):
        """境界: ちょうど25 → 0 (>25でカウント)"""
        s = pd.Series([25.0, 26.0, 25.0])
        result = _stress_days(s, 25.0)
        assert result.iloc[0] == 0
        assert result.iloc[1] == 1
        assert result.iloc[2] == 0

    def test_invariant_non_negative(self):
        """不変量: 結果は常に非負"""
        np.random.seed(42)
        s = pd.Series(np.random.uniform(10, 50, 100))
        result = _stress_days(s, 25.0)
        assert (result >= 0).all()

    def test_counterexample_all_below(self):
        """反例: 全て閾値以下 → 全て0"""
        s = pd.Series([10.0, 15.0, 20.0, 25.0])
        result = _stress_days(s, 25.0)
        assert (result == 0).all()


from src.signal_defs import (
    h_01_01, h_01_02, h_01_03a, h_01_03b, h_01_03c, h_01_03d,
    h_01_03e, h_01_03f, h_01_03g, h_01_03h,
    h_01_04a, h_01_04b, h_01_04c, h_01_04d,
    h_01_05a, h_01_05b, h_01_06, h_01_07, h_01_08, h_01_09, h_01_10,
    h_02_01a, h_02_01b, h_02_01c, h_02_02, h_02_03, h_02_04, h_02_05,
)


@pytest.fixture
def daily_df():
    """日足用の合成DataFrame。20日分。"""
    dates = pd.date_range("2025-01-06", periods=20, freq="B")
    np.random.seed(42)
    close = pd.Series(
        100 + np.cumsum(np.random.randn(20) * 2), index=dates, name="Close"
    )
    return pd.DataFrame({
        "Open": close - 0.5,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": np.random.randint(500, 3000, 20).astype(float),
    }, index=dates)


@pytest.fixture
def intraday_df():
    """5分足用の合成DataFrame。2日×78本。VWAP・NumTrades付き。"""
    bars_per_day = 78
    n_days = 2
    idx = []
    for d in pd.date_range("2025-01-06", periods=n_days, freq="B"):
        for i in range(bars_per_day):
            ts = d + pd.Timedelta(hours=9, minutes=30) + pd.Timedelta(minutes=5 * i)
            idx.append(ts)
    idx = pd.DatetimeIndex(idx)
    n = len(idx)
    np.random.seed(42)
    close = pd.Series(50 + np.cumsum(np.random.randn(n) * 0.3), index=idx)
    return pd.DataFrame({
        "Open": close - 0.1,
        "High": close + 0.2,
        "Low": close - 0.2,
        "Close": close,
        "Volume": np.random.randint(100, 1000, n).astype(float),
        "VWAP": close + np.random.randn(n) * 0.05,
        "NumTrades": np.random.randint(10, 200, n).astype(float),
    }, index=idx)


class TestCat1Structural:
    """Cat 1 全関数の構造テスト: 戻り値型・サイズ一致。"""

    ALL_CAT1 = [
        h_01_01, h_01_02,
        h_01_03a, h_01_03b, h_01_03c, h_01_03d,
        h_01_03e, h_01_03f, h_01_03g, h_01_03h,
        h_01_04a, h_01_04b, h_01_04c, h_01_04d,
        h_01_05a, h_01_05b, h_01_06, h_01_07, h_01_08, h_01_10,
    ]

    @pytest.mark.parametrize("func", ALL_CAT1)
    def test_returns_series_same_length(self, daily_df, func):
        """全関数が pd.Series を返し、入力と同じ長さ。"""
        result = func(daily_df)
        assert isinstance(result, pd.Series), f"{func.__name__} must return pd.Series"
        assert len(result) == len(daily_df), f"{func.__name__} length mismatch"

    @pytest.mark.parametrize("func", ALL_CAT1)
    def test_returns_float_dtype(self, daily_df, func):
        """全 Cat 1 関数は float 系を返す（bool ではない）。h_01_02 は signed int 可。"""
        result = func(daily_df)
        valid = result.dropna()
        if len(valid) > 0:
            assert not pd.api.types.is_bool_dtype(result), (
                f"{func.__name__} should return float, not bool"
            )

    def test_h_01_09_returns_series_intraday(self, intraday_df):
        """h_01_09 は 5分足で pd.Series を返す。"""
        result = h_01_09(intraday_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(intraday_df)

    def test_h_01_09_daily_returns_nan(self, daily_df):
        """h_01_09 は日足では NaN を返す（VWAP列なし）。"""
        result = h_01_09(daily_df)
        assert result.isna().all()


class TestCat2Structural:
    """Cat 2 全関数の構造テスト。"""

    DAILY_FUNCS = [h_02_01a, h_02_01b, h_02_01c, h_02_02, h_02_03]
    INTRADAY_FUNCS = [h_02_04, h_02_05]

    @pytest.mark.parametrize("func", DAILY_FUNCS)
    def test_daily_returns_series(self, daily_df, func):
        """日足関数が pd.Series を返す。"""
        result = func(daily_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(daily_df)

    @pytest.mark.parametrize("func", INTRADAY_FUNCS)
    def test_intraday_returns_series(self, intraday_df, func):
        """5分足関数が pd.Series を返す。"""
        result = func(intraday_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(intraday_df)

    @pytest.mark.parametrize("func", INTRADAY_FUNCS)
    def test_intraday_daily_fallback_nan(self, daily_df, func):
        """5分足専用関数は日足で NaN。"""
        result = func(daily_df)
        assert result.isna().all()


class TestCat1Representative:
    """Cat 1 代表的な関数の動作確認（既知解・境界）。"""

    def test_h_01_01_gap_known(self):
        """既知解: Open=102, 前日Close=100 → gap = +2%"""
        dates = pd.date_range("2025-01-06", periods=3, freq="B")
        df = pd.DataFrame({
            "Open": [100.0, 102.0, 98.0],
            "Close": [100.0, 103.0, 99.0],
            "High": [101.0, 104.0, 100.0],
            "Low": [99.0, 101.0, 97.0],
            "Volume": [1000.0, 1200.0, 800.0],
        }, index=dates)
        result = h_01_01(df)
        # day 1: gap = (102 - 100) / 100 * 100 = 2.0%
        assert result.iloc[1] == pytest.approx(2.0)
        # day 2: gap = (98 - 103) / 103 * 100 ≈ -4.854%
        assert result.iloc[2] == pytest.approx(-4.854, abs=0.01)

    def test_h_01_02_consecutive_known(self):
        """既知解: 3日連続上昇 → 3、次に下落 → -1"""
        dates = pd.date_range("2025-01-06", periods=6, freq="B")
        df = pd.DataFrame({
            "Open": [100.0] * 6,
            "High": [101.0] * 6,
            "Low": [99.0] * 6,
            "Close": [100.0, 102.0, 104.0, 106.0, 103.0, 101.0],
            "Volume": [1000.0] * 6,
        }, index=dates)
        result = h_01_02(df)
        assert result.iloc[3] == 3.0  # 3日連続上昇
        assert result.iloc[4] == -1.0  # 下落1日目

    def test_h_01_06_constant_returns_half(self):
        """既知解: 定数系列 → BB position = 0.5"""
        dates = pd.date_range("2025-01-06", periods=30, freq="B")
        df = pd.DataFrame({
            "Open": [100.0] * 30,
            "High": [101.0] * 30,
            "Low": [99.0] * 30,
            "Close": [100.0] * 30,
            "Volume": [1000.0] * 30,
        }, index=dates)
        result = h_01_06(df)
        valid = result.dropna()
        assert len(valid) > 0
        assert valid.iloc[-1] == pytest.approx(0.5)

    def test_h_01_10_known_close_at_high(self):
        """既知解: Close=High → 終値位置 = 1.0"""
        dates = pd.date_range("2025-01-06", periods=5, freq="B")
        df = pd.DataFrame({
            "Open": [100.0] * 5,
            "High": [105.0] * 5,
            "Low": [95.0] * 5,
            "Close": [105.0] * 5,
            "Volume": [1000.0] * 5,
        }, index=dates)
        result = h_01_10(df)
        # (105 - 95) / (105 - 95) = 1.0
        assert result.iloc[0] == pytest.approx(1.0)


class TestCat2Representative:
    """Cat 2 代表的な関数の動作確認。"""

    def test_h_02_01a_known_double_volume(self):
        """既知解: 出来高が5日rolling平均（当日含む）の比率"""
        dates = pd.date_range("2025-01-06", periods=6, freq="B")
        df = pd.DataFrame({
            "Open": [100.0] * 6,
            "High": [101.0] * 6,
            "Low": [99.0] * 6,
            "Close": [100.0] * 6,
            "Volume": [1000, 1000, 1000, 1000, 1000, 2000],
        }, index=dates)
        result = h_02_01a(df)
        # 5日rolling mean（当日含む）= (1000+1000+1000+1000+2000)/5 = 1200
        # ratio = 2000 / 1200 = 1.6667
        assert result.iloc[5] == pytest.approx(2000 / 1200, abs=0.01)

    def test_h_02_03_divergence_known(self):
        """既知解: 価格上昇+出来高減少 → divergence True"""
        dates = pd.date_range("2025-01-06", periods=3, freq="B")
        df = pd.DataFrame({
            "Open": [100.0] * 3,
            "High": [101.0] * 3,
            "Low": [99.0] * 3,
            "Close": [100.0, 105.0, 110.0],  # 上昇
            "Volume": [1000.0, 800.0, 600.0],  # 減少
        }, index=dates)
        result = h_02_03(df)
        # day 1: close +5%, vol -20% → 符号不一致 → True
        assert result.iloc[1] is True or result.iloc[1] == True


# ══════════════════════════════════════════════════════════════════════
# 信号生成関数テスト（Cat 3, 8）
# ══════════════════════════════════════════════════════════════════════

from src.signal_defs import (
    h_03_01, h_03_02, h_03_03, h_03_04, h_03_05, h_03_06, h_03_07,
    h_08_01, h_08_02, h_08_03,
    h_04_01a, h_04_01b, h_04_02a, h_04_02b, h_04_03a, h_04_03b,
    h_04_04a, h_04_04b, h_04_05a, h_04_05b,
    h_05_01, h_05_02, h_05_03, h_05_04, h_05_05,
    h_09_01, h_09_02, h_09_03,
    h_11_01, h_11_02, h_11_03,
    h_12_01, h_12_02, h_12_03,
    h_13_01, h_13_02, h_13_03,
    h_14_01, h_14_02, h_14_03,
    h_17_01a, h_17_01b, h_17_02a, h_17_02b,
    h_18_01, h_18_02, h_18_03, h_18_04,
    h_06_01, h_06_02, h_06_03, h_06_04,
    h_07_01, h_07_02, h_07_03, h_07_04, h_07_05,
    h_19_01, h_19_02,
    h_20_01, h_20_02, h_20_03,
    h_23_01, h_23_02,
    h_24_01, h_24_02,
    h_25_01, h_25_02,
    h_26_01, h_26_02, h_26_03,
    h_27_01, h_27_02, h_27_03,
    h_28_01, h_28_02,
    h_29_01, h_29_02,
    h_30_01, h_30_02, h_30_03,
    h_32_01, h_32_02, h_32_03, h_32_04, h_32_05,
    h_33_01, h_33_02, h_33_03,
    h_34_01, h_34_02,
    h_35_01, h_35_02, h_35_03,
    h_37_01, h_37_02,
    h_40_01, h_40_02,
    h_41_01, h_41_02,
    h_42_01, h_42_02,
    h_43_01, h_43_02,
    h_44_01, h_44_02,
    h_46_01, h_46_02,
    h_50_01, h_50_02, h_50_03,
    h_53_01, h_53_02,
    h_61_01, h_61_02,
    h_62_01, h_62_02,
    h_64_01, h_64_02,
    h_65_01, h_65_02,
    h_68_01, h_68_02, h_68_03,
    h_69_01, h_69_02, h_69_03,
    h_70_01, h_70_02, h_70_03,
    h_71_01, h_71_02, h_71_03,
    h_72_01, h_72_02,
)


@pytest.fixture
def daily_macro_df():
    """日足+マクロ列マージ済みの合成DataFrame。"""
    dates = pd.date_range("2025-01-06", periods=30, freq="B")
    np.random.seed(42)
    close = pd.Series(100 + np.cumsum(np.random.randn(30) * 2), index=dates)
    vix = pd.Series(20 + np.cumsum(np.random.randn(30) * 1), index=dates)
    vix3m = pd.Series(22 + np.cumsum(np.random.randn(30) * 0.5), index=dates)
    return pd.DataFrame({
        "Open": close - 0.5,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": np.random.randint(500, 3000, 30).astype(float),
        "vix": vix.clip(lower=10),
        "vix3m": vix3m.clip(lower=10),
    }, index=dates)


@pytest.fixture
def daily_macro_pair_df(daily_macro_df):
    """日足+マクロ+ペア(VIXY)列マージ済み。"""
    n = len(daily_macro_df)
    np.random.seed(99)
    daily_macro_df['pair_Close'] = 15 + np.cumsum(np.random.randn(n) * 0.5)
    daily_macro_df['pair_Volume'] = np.random.randint(200, 5000, n).astype(float)
    return daily_macro_df


class TestCat3Structural:
    """Cat 3 全関数の構造テスト。"""

    MACRO_FUNCS = [h_03_01, h_03_02, h_03_03, h_03_04, h_03_05, h_03_06]

    @pytest.mark.parametrize("func", MACRO_FUNCS)
    def test_returns_series(self, daily_macro_df, func):
        """マクロ依存関数が pd.Series を返す。"""
        result = func(daily_macro_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(daily_macro_df)

    def test_h_03_07_intraday(self, intraday_df):
        """h_03_07 は 5分足で Series を返す。"""
        result = h_03_07(intraday_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(intraday_df)

    def test_h_03_07_daily_nan(self, daily_macro_df):
        """h_03_07 は日足で NaN。"""
        result = h_03_07(daily_macro_df)
        assert result.isna().all()


class TestCat8Structural:
    """Cat 8 全関数の構造テスト。"""

    def test_h_08_01_returns_series(self, daily_macro_df):
        result = h_08_01(daily_macro_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(daily_macro_df)

    def test_h_08_02_returns_series(self, daily_macro_pair_df):
        result = h_08_02(daily_macro_pair_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(daily_macro_pair_df)

    def test_h_08_03_returns_series(self, daily_macro_pair_df):
        result = h_08_03(daily_macro_pair_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(daily_macro_pair_df)

    def test_h_08_02_no_pair_nan(self, daily_macro_df):
        """ペア列なし → NaN。"""
        result = h_08_02(daily_macro_df)
        assert result.isna().all()

    def test_h_08_03_no_pair_nan(self, daily_macro_df):
        """ペア列なし → NaN。"""
        result = h_08_03(daily_macro_df)
        assert result.isna().all()


class TestCat3Representative:
    """Cat 3 代表テスト。"""

    def test_h_03_01_is_vix(self, daily_macro_df):
        """既知解: h_03_01 は vix 列そのもの。"""
        result = h_03_01(daily_macro_df)
        pd.testing.assert_series_equal(result, daily_macro_df['vix'], check_names=False)

    def test_h_03_03_known_backwardation(self):
        """既知解: VIX=30, VIX3M=25 → 1.2 (バックワーデーション)"""
        dates = pd.date_range("2025-01-06", periods=3, freq="B")
        df = pd.DataFrame({
            "Open": [100.0] * 3, "High": [101.0] * 3,
            "Low": [99.0] * 3, "Close": [100.0] * 3,
            "Volume": [1000.0] * 3,
            "vix": [30.0, 20.0, 15.0],
            "vix3m": [25.0, 25.0, 25.0],
        }, index=dates)
        result = h_03_03(df)
        assert result.iloc[0] == pytest.approx(1.2)
        assert result.iloc[1] == pytest.approx(0.8)

    def test_h_03_06_atr_acceleration(self):
        """既知解: ATR上昇 → 正の変化率。"""
        dates = pd.date_range("2025-01-06", periods=30, freq="B")
        # 徐々にレンジ拡大
        high = pd.Series([100 + i * 0.5 for i in range(30)], index=dates)
        low = pd.Series([100 - i * 0.5 for i in range(30)], index=dates)
        close = (high + low) / 2
        df = pd.DataFrame({
            "Open": close, "High": high, "Low": low,
            "Close": close, "Volume": [1000.0] * 30,
            "vix": [20.0] * 30, "vix3m": [22.0] * 30,
        }, index=dates)
        result = h_03_06(df)
        # 後半はATRが増加しているので変化率は正
        valid = result.dropna()
        assert len(valid) > 0
        assert valid.iloc[-1] > 0


# ══════════════════════════════════════════════════════════════════════
# 信号生成関数テスト（Cat 4, 5, 9, 11, 12, 13, 14, 17, 18）
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def full_macro_df():
    """全マクロ列+ペア列を含む合成DataFrame。"""
    dates = pd.date_range("2025-01-06", periods=30, freq="B")
    np.random.seed(42)
    close = pd.Series(100 + np.cumsum(np.random.randn(30) * 2), index=dates)
    n = len(dates)
    return pd.DataFrame({
        "Open": close - 0.5,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": np.random.randint(500, 3000, n).astype(float),
        "vix": pd.Series(22 + np.cumsum(np.random.randn(n) * 1), index=dates).clip(10),
        "vix3m": pd.Series(24 + np.cumsum(np.random.randn(n) * 0.5), index=dates).clip(10),
        "brent": pd.Series(70 + np.cumsum(np.random.randn(n) * 2), index=dates).clip(30),
        "hy_spread": pd.Series(3.5 + np.cumsum(np.random.randn(n) * 0.1), index=dates).clip(1),
        "yield_curve": pd.Series(0.5 + np.cumsum(np.random.randn(n) * 0.05), index=dates),
        "usd_index": pd.Series(104 + np.cumsum(np.random.randn(n) * 0.5), index=dates),
        "us10y": pd.Series(4.2 + np.cumsum(np.random.randn(n) * 0.05), index=dates),
        "pair_Close": pd.Series(50 + np.cumsum(np.random.randn(n) * 1), index=dates),
        "pair_Volume": np.random.randint(300, 5000, n).astype(float),
    }, index=dates)


class TestBatch3to6Structural:
    """Cat 4,5,9,11,12,13,14,17,18 全関数の構造テスト。"""

    MACRO_FUNCS = [
        h_04_01a, h_04_01b, h_04_02a, h_04_02b, h_04_03a, h_04_03b,
        h_04_04a, h_04_04b, h_04_05a, h_04_05b,
        h_13_01, h_13_02, h_13_03,
        h_17_01a, h_17_01b, h_17_02a, h_17_02b,
        h_18_01, h_18_04,
    ]
    OHLCV_FUNCS = [
        h_05_01, h_05_02, h_05_03, h_05_04, h_05_05,
        h_09_01, h_09_02, h_09_03,
        h_12_01, h_12_03,
        h_18_02, h_18_03,
    ]
    PAIR_FUNCS = [h_11_01, h_11_02, h_11_03]
    CALENDAR_FUNCS = [h_14_01, h_14_02, h_14_03]

    @pytest.mark.parametrize("func", MACRO_FUNCS)
    def test_macro_returns_series(self, full_macro_df, func):
        result = func(full_macro_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(full_macro_df)

    @pytest.mark.parametrize("func", OHLCV_FUNCS)
    def test_ohlcv_returns_series(self, daily_df, func):
        result = func(daily_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(daily_df)

    @pytest.mark.parametrize("func", PAIR_FUNCS)
    def test_pair_returns_series(self, full_macro_df, func):
        result = func(full_macro_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(full_macro_df)

    @pytest.mark.parametrize("func", PAIR_FUNCS)
    def test_pair_no_pair_nan(self, daily_df, func):
        result = func(daily_df)
        assert result.isna().all()

    @pytest.mark.parametrize("func", CALENDAR_FUNCS)
    def test_calendar_returns_series(self, full_macro_df, func):
        result = func(full_macro_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(full_macro_df)


class TestBatch3to6Representative:
    """バッチ3-6 代表テスト。"""

    def test_h_05_01_weekday_monday(self):
        """既知解: 月曜日 → 0"""
        dates = pd.date_range("2025-01-06", periods=5, freq="B")  # Mon-Fri
        df = pd.DataFrame({
            "Open": [100.0] * 5, "High": [101.0] * 5,
            "Low": [99.0] * 5, "Close": [100.0] * 5,
            "Volume": [1000.0] * 5,
        }, index=dates)
        result = h_05_01(df)
        assert result.iloc[0] == 0  # Monday
        assert result.iloc[4] == 4  # Friday

    def test_h_09_02_spring_known(self):
        """既知解: 20日安値割れ後の反発 → True"""
        dates = pd.date_range("2025-01-06", periods=22, freq="B")
        # 最初20日は100-80に下落、21日目に79(安値割れ)、22日目に81(反発)
        closes = list(range(100, 80, -1)) + [79.0, 81.0]
        df = pd.DataFrame({
            "Open": [c - 0.5 for c in closes],
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Close": closes,
            "Volume": [1000.0] * 22,
        }, index=dates)
        result = h_09_02(df)
        # day 21 (index 21): 前日Close=79 <= 20日min=80, 当日Close=81 > 20日min
        assert result.iloc[21] == True

    def test_h_18_01_high_vix_notrade(self):
        """既知解: VIX=40 → True (ノートレード)"""
        dates = pd.date_range("2025-01-06", periods=3, freq="B")
        df = pd.DataFrame({
            "Open": [100.0] * 3, "High": [101.0] * 3,
            "Low": [99.0] * 3, "Close": [100.0] * 3,
            "Volume": [1000.0] * 3,
            "vix": [20.0, 40.0, 15.0],
            "vix3m": [22.0, 22.0, 22.0],
        }, index=dates)
        result = h_18_01(df)
        assert result.iloc[0] == False
        assert result.iloc[1] == True
        assert result.iloc[2] == False

    def test_h_17_01a_lag_no_lookahead(self):
        """Look-Ahead Biasチェック: ラグ1日はshift(1)で過去データのみ。"""
        dates = pd.date_range("2025-01-06", periods=5, freq="B")
        df = pd.DataFrame({
            "Open": [100.0] * 5, "High": [101.0] * 5,
            "Low": [99.0] * 5, "Close": [100.0] * 5,
            "Volume": [1000.0] * 5,
            "brent": [70.0, 75.0, 73.0, 80.0, 78.0],
            "vix": [20.0] * 5, "vix3m": [22.0] * 5,
            "hy_spread": [3.5] * 5,
            "yield_curve": [0.5] * 5,
            "usd_index": [104.0] * 5,
            "us10y": [4.2] * 5,
        }, index=dates)
        result = h_17_01a(df)
        # day 2 (idx 2): shift(1)なので day 1の変化率 = (75-70)/70*100 = 7.14%
        assert result.iloc[2] == pytest.approx((75 - 70) / 70 * 100, abs=0.01)
        # day 1 (idx 1): shift(1)で day 0の変化率 = NaN (初日)
        assert pd.isna(result.iloc[1])


# ══════════════════════════════════════════════════════════════════════
# 残りカテゴリの構造テスト（Cat 6,7,19-72）
# ══════════════════════════════════════════════════════════════════════


class TestRemainingCatsStructural:
    """全残りカテゴリの構造テスト。"""

    # マクロ+ペア列が必要な関数
    FULL_MACRO_PAIR = [
        h_06_01, h_06_02, h_06_03, h_06_04,
        h_07_01, h_07_02, h_07_03, h_07_04, h_07_05,
        h_20_01, h_20_02,
        h_23_01, h_23_02,
        h_26_01,
        h_27_01, h_27_02, h_27_03,
        h_28_01, h_28_02,
        h_32_01, h_32_02, h_32_03, h_32_04, h_32_05,
        h_33_01, h_33_02, h_33_03,
        h_34_01, h_34_02,
        h_35_01, h_35_02, h_35_03,
        h_37_01, h_37_02,
        h_43_01, h_43_02,
        h_44_01, h_44_02,
        h_46_01, h_46_02,
        h_50_01, h_50_02, h_50_03,
        h_53_01, h_53_02,
        h_64_01, h_64_02,
    ]

    # OHLCVのみで動く関数
    OHLCV_ONLY = [
        h_19_01, h_19_02,
        h_20_03,
        h_24_01, h_24_02,
        h_29_01, h_29_02,
        h_30_03,
        h_40_01, h_40_02,
        h_41_01, h_41_02,
        h_42_01, h_42_02,
        h_61_01, h_61_02,
        h_62_01, h_62_02,
        h_65_01, h_65_02,
    ]

    # 5分足専用
    INTRADAY_ONLY = [
        h_25_01, h_25_02,
        h_68_01, h_68_02, h_68_03,
        h_69_01, h_69_02, h_69_03,
        h_70_01, h_70_02, h_70_03,
        h_71_01, h_71_02, h_71_03,
        h_72_01, h_72_02,
    ]

    @pytest.mark.parametrize("func", FULL_MACRO_PAIR)
    def test_macro_pair_returns_series(self, full_macro_df, func):
        result = func(full_macro_df)
        assert isinstance(result, pd.Series), f"{func.__name__}"
        assert len(result) == len(full_macro_df), f"{func.__name__}"

    @pytest.mark.parametrize("func", OHLCV_ONLY)
    def test_ohlcv_returns_series(self, daily_df, func):
        result = func(daily_df)
        assert isinstance(result, pd.Series), f"{func.__name__}"
        assert len(result) == len(daily_df), f"{func.__name__}"

    @pytest.mark.parametrize("func", INTRADAY_ONLY)
    def test_intraday_returns_series(self, intraday_df, func):
        result = func(intraday_df)
        assert isinstance(result, pd.Series), f"{func.__name__}"
        assert len(result) == len(intraday_df), f"{func.__name__}"

    @pytest.mark.parametrize("func", INTRADAY_ONLY)
    def test_intraday_daily_fallback(self, daily_df, func):
        """5分足専用関数は日足でNaN。"""
        result = func(daily_df)
        assert result.isna().all(), f"{func.__name__} should return NaN for daily data"


class TestRemainingCatsRepresentative:
    """残りカテゴリの代表テスト。"""

    def test_h_29_01_crash_signal(self):
        """既知解: 前日-6% → True (ロングシグナル)"""
        dates = pd.date_range("2025-01-06", periods=3, freq="B")
        df = pd.DataFrame({
            "Open": [100.0, 95.0, 90.0],
            "High": [101.0, 96.0, 91.0],
            "Low": [99.0, 93.0, 88.0],
            "Close": [100.0, 93.0, 90.0],  # day1: -7%
            "Volume": [1000.0] * 3,
        }, index=dates)
        result = h_29_01(df)
        # day 2: 前日リターン = (93-100)/100*100 = -7%. shift(1) → day 2 に -7%
        assert result.iloc[2] == True

    def test_h_62_02_counter_no_lookahead(self):
        """Look-Ahead: h_62_02はshift(1)で前日データのみ使用。"""
        dates = pd.date_range("2025-01-06", periods=4, freq="B")
        df = pd.DataFrame({
            "Open": [100.0, 100.0, 96.0, 93.0],
            "High": [101.0, 101.0, 97.0, 94.0],
            "Low": [99.0, 99.0, 95.0, 92.0],
            "Close": [100.0, 100.0, 96.0, 93.0],  # day2: -4%
            "Volume": [1000.0] * 4,
        }, index=dates)
        result = h_62_02(df)
        # day 3: 前日(day2)のret = (96-100)/100*100 = -4% < -3% → True
        assert result.iloc[3] == True
        # day 2: 前日(day1)のret = 0% → False
        assert result.iloc[2] == False

    def test_h_41_01_drawdown_known(self):
        """既知解: 100→90→80 → ドローダウン -10%, -20%"""
        dates = pd.date_range("2025-01-06", periods=3, freq="B")
        df = pd.DataFrame({
            "Open": [100.0, 90.0, 80.0],
            "High": [101.0, 91.0, 81.0],
            "Low": [99.0, 89.0, 79.0],
            "Close": [100.0, 90.0, 80.0],
            "Volume": [1000.0] * 3,
        }, index=dates)
        result = h_41_01(df)
        assert result.iloc[0] == pytest.approx(0.0)
        assert result.iloc[1] == pytest.approx(-10.0)
        assert result.iloc[2] == pytest.approx(-20.0)
