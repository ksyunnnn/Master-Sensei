"""フロー/モメンタム判定ロジック

レジーム（マクロ背景環境）とは独立した軸として、
直近の価格・出来高・VIXの「方向と勢い」をスコアリングする。

K-022: risk_off環境でもイベントドリブンの急反転でSOXL+17.9%が発生。
レジームだけではエントリー判断に不十分。フロー軸が必要。

指標分類:
  - PRICE_MOMENTUM: 1日/3日リターンの方向と大きさ
  - VIX_CHANGE: VIX日次変化率（恐怖の緩和/悪化速度）
  - VOLUME_SURGE: 出来高/20日平均（参加者のconviction）
  - SIGMA_POSITION: (終値-SMA20)/σ20（平均からの乖離）

閾値の根拠:
  2025-03〜2026-03の1年間、8銘柄の日足データの分位点を使用。
  P90/P10を「強い」、P75/P25を「やや」、中間を「neutral」。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from src.regime import IndicatorAssessment


@dataclass
class FlowAssessment:
    """統合フロー判定結果"""
    overall: str           # bullish / neutral / bearish / unknown
    overall_score: float   # -2.0 to +2.0 の加重平均
    symbol: str            # 評価対象銘柄
    indicators: list[IndicatorAssessment]
    reasoning: str


def assess_price_momentum(
    daily_return_1d: Optional[float] = None,
    daily_return_3d: Optional[float] = None,
) -> IndicatorAssessment:
    """価格モメンタム判定

    閾値根拠（1年8銘柄データ）:
      1日リターン: P90=±5%, P95=±7.5%
      3日リターン: P90=±8.6%, P95=±13.2%

      ±7.5%(1d) / ±13%(3d) 超: strong（P95超の極端な動き）
      ±5%(1d) / ±8.5%(3d) 超: bullish/bearish（P90超）
      それ以内: neutral
    """
    # 1dと3dの加重平均スコア（1d重み1.5、3d重み1.0）
    scores = []
    weights = []

    if daily_return_1d is not None:
        scores.append(_momentum_score(daily_return_1d, 0.05, 0.075))
        weights.append(1.5)

    if daily_return_3d is not None:
        scores.append(_momentum_score(daily_return_3d, 0.085, 0.13))
        weights.append(1.0)

    if not scores:
        return IndicatorAssessment("PRICE_MOMENTUM", 0.0, "unknown", 0, "データなし")

    weighted = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
    score = round(weighted)

    # 代表値（1dを優先表示）
    val = daily_return_1d if daily_return_1d is not None else daily_return_3d

    regime_map = {2: "strong_bullish", 1: "bullish", 0: "neutral", -1: "bearish", -2: "strong_bearish"}
    regime = regime_map.get(score, "neutral")

    return IndicatorAssessment(
        "PRICE_MOMENTUM", val, regime, score,
        f"1d={_fmt_pct(daily_return_1d)} 3d={_fmt_pct(daily_return_3d)}"
    )


def _momentum_score(ret: float, threshold_mild: float, threshold_strong: float) -> int:
    if ret > threshold_strong:
        return 2
    elif ret > threshold_mild:
        return 1
    elif ret > -threshold_mild:
        return 0
    elif ret > -threshold_strong:
        return -1
    else:
        return -2


def _fmt_pct(val: Optional[float]) -> str:
    if val is None:
        return "---"
    return f"{val:+.1%}"


def assess_vix_change(vix_change_1d: float) -> IndicatorAssessment:
    """VIX日次変化率の判定

    閾値根拠（1年データ）:
      P10=-8.2%, P25=-4.2%, P75=+4.3%, P90=+10.2%

      < -12%: sharp_drop（P05未満、恐怖の急速な緩和）→ bullish
      -12% to -8%: dropping（P10付近）→ やや bullish
      -8% to +8%: stable（P10-P90の中間）→ neutral
      +8% to +12%: rising → やや bearish
      > +12%: spiking → bearish
    """
    if vix_change_1d < -0.12:
        return IndicatorAssessment(
            "VIX_CHANGE", vix_change_1d, "sharp_drop", 2,
            f"VIX変化{vix_change_1d:+.1%}: 急落（恐怖緩和）"
        )
    elif vix_change_1d < -0.08:
        return IndicatorAssessment(
            "VIX_CHANGE", vix_change_1d, "dropping", 1,
            f"VIX変化{vix_change_1d:+.1%}: 低下中"
        )
    elif vix_change_1d <= 0.08:
        return IndicatorAssessment(
            "VIX_CHANGE", vix_change_1d, "stable", 0,
            f"VIX変化{vix_change_1d:+.1%}: 安定"
        )
    elif vix_change_1d <= 0.12:
        return IndicatorAssessment(
            "VIX_CHANGE", vix_change_1d, "rising", -1,
            f"VIX変化{vix_change_1d:+.1%}: 上昇中"
        )
    else:
        return IndicatorAssessment(
            "VIX_CHANGE", vix_change_1d, "spiking", -2,
            f"VIX変化{vix_change_1d:+.1%}: 急騰（恐怖拡大）"
        )


def assess_volume_surge(volume_ratio: float, price_direction: int = 0) -> IndicatorAssessment:
    """出来高サージ判定（出来高/20日平均 × 価格方向）

    出来高は方向を持たない「増幅器」。price_directionと連動して
    上昇+サージ=bullish conviction、下落+サージ=bearish convictionとする。

    price_direction: +1(上昇), -1(下落), 0(不明)

    閾値根拠（1年8銘柄データ）:
      P25=0.77, P50=0.95, P75=1.19, P90=1.49

      > 1.5: surge（P90超）→ magnitude 2
      1.2-1.5: above_avg（P75-P90）→ magnitude 1
      0.7-1.2: normal → magnitude 0
      < 0.7: low → magnitude 0（薄商い = conviction不足だが減点しない）
    """
    if volume_ratio > 1.5:
        magnitude = 2
        regime = "surge"
        label = "サージ"
    elif volume_ratio > 1.2:
        magnitude = 1
        regime = "above_avg"
        label = "平均以上"
    elif volume_ratio >= 0.7:
        magnitude = 0
        regime = "normal"
        label = "通常"
    else:
        magnitude = 0
        regime = "low"
        label = "薄商い"

    score = magnitude * price_direction

    return IndicatorAssessment(
        "VOLUME_SURGE", volume_ratio, regime, score,
        f"出来高{volume_ratio:.1f}x: {label}"
    )


def assess_sigma_position(sigma: float) -> IndicatorAssessment:
    """σポジション判定（(Close-SMA20)/std20）

    閾値根拠（1年8銘柄データ）:
      P05=-1.98, P10=-1.63, P25=-1.06, P75=+1.10, P90=+1.73, P95=+2.03

      > +2.0: extreme_high（P95超）
      +1.0 to +2.0: above_mean（P75-P95）
      -1.0 to +1.0: at_mean（P25-P75）
      -2.0 to -1.0: below_mean（P25-P05）
      < -2.0: extreme_low（P05未満）
    """
    if sigma > 2.0:
        return IndicatorAssessment(
            "SIGMA_POSITION", sigma, "extreme_high", 2,
            f"σ={sigma:+.2f}: SMA20大幅上方"
        )
    elif sigma > 1.0:
        return IndicatorAssessment(
            "SIGMA_POSITION", sigma, "above_mean", 1,
            f"σ={sigma:+.2f}: SMA20上方"
        )
    elif sigma >= -1.0:
        return IndicatorAssessment(
            "SIGMA_POSITION", sigma, "at_mean", 0,
            f"σ={sigma:+.2f}: SMA20付近"
        )
    elif sigma >= -2.0:
        return IndicatorAssessment(
            "SIGMA_POSITION", sigma, "below_mean", -1,
            f"σ={sigma:+.2f}: SMA20下方"
        )
    else:
        return IndicatorAssessment(
            "SIGMA_POSITION", sigma, "extreme_low", -2,
            f"σ={sigma:+.2f}: SMA20大幅下方"
        )


def compute_flow_inputs(
    daily_df: pd.DataFrame,
    vix_df: pd.DataFrame,
) -> dict:
    """Parquetの日足・VIXデータから assess_flow() の入力値を計算する。

    Args:
        daily_df: 日足DataFrame（index=Date, columns含む: Close, Volume）
        vix_df: VIXマクロDataFrame（index=Date, columns含む: value）

    Returns:
        dict with keys: daily_return_1d, daily_return_3d, vix_change_1d,
                        volume_ratio, sigma_position
        データ不足の場合、該当キーはNone。
    """
    result = {
        "daily_return_1d": None,
        "daily_return_3d": None,
        "vix_change_1d": None,
        "volume_ratio": None,
        "sigma_position": None,
    }

    if daily_df.empty or len(daily_df) < 2:
        return result

    closes = daily_df["Close"]

    # daily_return_1d: (最終日 - 前日) / 前日
    result["daily_return_1d"] = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]

    # daily_return_3d: (最終日 - 3日前) / 3日前
    if len(daily_df) >= 4:
        result["daily_return_3d"] = (closes.iloc[-1] - closes.iloc[-4]) / closes.iloc[-4]

    # volume_ratio: 最終日Volume / 20日平均Volume
    if len(daily_df) >= 21 and "Volume" in daily_df.columns:
        vol_20d_avg = daily_df["Volume"].iloc[-21:-1].mean()
        if vol_20d_avg > 0:
            result["volume_ratio"] = float(daily_df["Volume"].iloc[-1] / vol_20d_avg)

    # sigma_position: (Close - SMA20) / std20
    if len(daily_df) >= 21:
        sma20 = closes.iloc[-20:].mean()
        std20 = closes.iloc[-20:].std()
        if std20 > 0:
            result["sigma_position"] = float((closes.iloc[-1] - sma20) / std20)

    # vix_change_1d: (最終日VIX - 前日VIX) / 前日VIX
    if not vix_df.empty and len(vix_df) >= 2:
        vix_vals = vix_df["value"]
        result["vix_change_1d"] = float(
            (vix_vals.iloc[-1] - vix_vals.iloc[-2]) / vix_vals.iloc[-2]
        )

    return result


# フロー指標の重み
FLOW_WEIGHTS = {
    "PRICE_MOMENTUM": 2.0,   # 最重要: 直近の方向と勢い
    "VIX_CHANGE": 1.5,       # VIXの変化速度はレジーム転換の先行指標
    "VOLUME_SURGE": 1.0,     # convictionの確認（方向は他指標に依存）
    "SIGMA_POSITION": 0.5,   # 乖離度は逆張り/順張りの文脈指標
}


def assess_flow(
    symbol: str,
    daily_return_1d: Optional[float] = None,
    daily_return_3d: Optional[float] = None,
    vix_change_1d: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    sigma_position: Optional[float] = None,
) -> FlowAssessment:
    """統合フロー判定

    各指標を独立に評価し、加重平均で統合する（MAP方式）。
    レジーム（assess_regime）とは独立した軸。
    """
    indicators = []

    # PRICE_MOMENTUMを先に評価し、方向をVOLUME_SURGEに渡す
    momentum_ind = None
    if daily_return_1d is not None or daily_return_3d is not None:
        momentum_ind = assess_price_momentum(daily_return_1d, daily_return_3d)
        indicators.append(momentum_ind)

    if vix_change_1d is not None:
        indicators.append(assess_vix_change(vix_change_1d))

    if volume_ratio is not None:
        # 価格方向をPRICE_MOMENTUMスコアの符号から導出
        if momentum_ind is not None and momentum_ind.score != 0:
            price_direction = 1 if momentum_ind.score > 0 else -1
        else:
            price_direction = 0
        indicators.append(assess_volume_surge(volume_ratio, price_direction))

    if sigma_position is not None:
        indicators.append(assess_sigma_position(sigma_position))

    if not indicators:
        return FlowAssessment("unknown", 0.0, symbol, [], "データなし")

    # 加重平均スコア
    total_weight = sum(FLOW_WEIGHTS.get(ind.name, 1.0) for ind in indicators)
    weighted_score = sum(
        ind.score * FLOW_WEIGHTS.get(ind.name, 1.0) for ind in indicators
    ) / total_weight

    # 分類
    if weighted_score > 0.5:
        overall = "bullish"
    elif weighted_score > -0.5:
        overall = "neutral"
    else:
        overall = "bearish"

    parts = [ind.note for ind in indicators]
    reasoning = "。".join(parts)

    return FlowAssessment(
        overall=overall,
        overall_score=round(weighted_score, 2),
        symbol=symbol,
        indicators=indicators,
        reasoning=reasoning,
    )
