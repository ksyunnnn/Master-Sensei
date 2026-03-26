"""レジーム判定ロジック

各指標を独立にスコアリングし、最後に統合する（Charter 3.3 MAP方式）。
先に結論を出してから要素を評価しない。

指標分類:
  - VIX水準: ボラティリティの絶対水準
  - VIXターム構造: VIX/VIX3M比率。>1.0はバックワーデーション（短期恐怖）
  - HYスプレッド: クレジットストレス
  - イールドカーブ: 景気サイクル
  - 原油: 地政学リスク + インフレ圧力
  - ドル指数: グローバル金融環境

閾値の根拠:
  2025-03〜2026-03の1年間データの分位点を使用。
  extreme = P90超、elevated = P75超、normal = P25-P75、low = P25未満。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class IndicatorAssessment:
    """個別指標の判定結果"""
    name: str
    value: float
    regime: str  # low / normal / elevated / extreme / contango / backwardation etc.
    score: int   # -2 (strong risk-off) to +2 (strong risk-on)
    note: str


@dataclass
class RegimeAssessment:
    """統合レジーム判定結果"""
    overall: str  # risk_on / neutral / risk_off
    overall_score: float  # -2.0 to +2.0 の加重平均
    indicators: list[IndicatorAssessment]
    reasoning: str


def assess_vix(value: float) -> IndicatorAssessment:
    """VIX水準の判定

    閾値根拠（1年データ）:
      P25=16.15, P50=17.38, P75=20.78, P90=24.99
      < 16: low → risk-on（恐怖なし）
      16-20: normal
      20-25: elevated → やや risk-off
      25-35: high → risk-off
      > 35: extreme → strong risk-off
    """
    if value < 16:
        return IndicatorAssessment("VIX", value, "low", 2, f"VIX {value:.1f} < 16: 恐怖なし")
    elif value < 20:
        return IndicatorAssessment("VIX", value, "normal", 1, f"VIX {value:.1f}: 通常範囲")
    elif value < 25:
        return IndicatorAssessment("VIX", value, "elevated", -1, f"VIX {value:.1f}: 警戒水準")
    elif value < 35:
        return IndicatorAssessment("VIX", value, "high", -2, f"VIX {value:.1f} > 25: リスクオフ")
    else:
        return IndicatorAssessment("VIX", value, "extreme", -2, f"VIX {value:.1f} > 35: パニック")


def assess_vix_term_structure(ratio: float) -> IndicatorAssessment:
    """VIXターム構造（VIX/VIX3M比率）の判定

    閾値根拠:
      < 0.85: steep contango → risk-on（長期が高い＝構造的に落ち着き）
      0.85-0.95: normal contango
      0.95-1.0: flat → 警戒
      > 1.0: backwardation → risk-off（短期恐怖 > 長期）
      データ上バックワーデーションは全体の10.4%
    """
    if ratio < 0.85:
        return IndicatorAssessment("VIX_TERM", ratio, "steep_contango", 2, f"VIX/VIX3M {ratio:.3f}: 急勾配コンタンゴ")
    elif ratio < 0.95:
        return IndicatorAssessment("VIX_TERM", ratio, "contango", 1, f"VIX/VIX3M {ratio:.3f}: 通常コンタンゴ")
    elif ratio < 1.0:
        return IndicatorAssessment("VIX_TERM", ratio, "flat", 0, f"VIX/VIX3M {ratio:.3f}: フラット化（警戒）")
    else:
        return IndicatorAssessment("VIX_TERM", ratio, "backwardation", -2, f"VIX/VIX3M {ratio:.3f}: バックワーデーション")


def assess_hy_spread(value: float) -> IndicatorAssessment:
    """HYスプレッドの判定

    閾値根拠（1年データ）:
      P25=2.84, P50=2.95, P75=3.17, P90=3.51
      < 2.8: tight → risk-on
      2.8-3.2: normal
      3.2-3.5: widening → 警戒
      > 3.5: stressed → risk-off
      歴史的に > 5.0 は危機水準だが、1年データにはなし
    """
    if value < 2.8:
        return IndicatorAssessment("HY_SPREAD", value, "tight", 2, f"HYスプレッド {value:.2f}: タイト")
    elif value < 3.2:
        return IndicatorAssessment("HY_SPREAD", value, "normal", 1, f"HYスプレッド {value:.2f}: 通常")
    elif value < 3.5:
        return IndicatorAssessment("HY_SPREAD", value, "widening", -1, f"HYスプレッド {value:.2f}: 拡大傾向")
    else:
        return IndicatorAssessment("HY_SPREAD", value, "stressed", -2, f"HYスプレッド {value:.2f}: ストレス")


def assess_yield_curve(value: float) -> IndicatorAssessment:
    """イールドカーブ（10Y-2Y）の判定

    閾値根拠:
      < 0: inverted → 景気後退シグナル（今の1年データにはなし。最低0.29）
      0-0.3: flat → 警戒
      0.3-0.6: normal
      > 0.6: steep → 景気回復/拡大期
    """
    if value < 0:
        return IndicatorAssessment("YIELD_CURVE", value, "inverted", -2, f"YC {value:.2f}: 逆イールド")
    elif value < 0.3:
        return IndicatorAssessment("YIELD_CURVE", value, "flat", -1, f"YC {value:.2f}: フラット")
    elif value <= 0.6:
        return IndicatorAssessment("YIELD_CURVE", value, "normal", 1, f"YC {value:.2f}: 正常")
    else:
        return IndicatorAssessment("YIELD_CURVE", value, "steep", 2, f"YC {value:.2f}: スティープ")


def assess_oil(value: float) -> IndicatorAssessment:
    """原油（Brent）の判定

    閾値根拠（1年データ）:
      P25=64.70, P50=67.48, P75=70.62, P90=74.72
      通常期はP25-P75の$65-71だが、現在$100超の異常値圏
      < 70: normal
      70-85: elevated
      85-100: high → 地政学リスク・インフレ圧力
      > 100: crisis → 供給ショック水準
    """
    if value < 70:
        return IndicatorAssessment("OIL", value, "normal", 1, f"Brent ${value:.1f}: 通常")
    elif value < 85:
        return IndicatorAssessment("OIL", value, "elevated", 0, f"Brent ${value:.1f}: やや高い")
    elif value < 100:
        return IndicatorAssessment("OIL", value, "high", -1, f"Brent ${value:.1f}: 高水準")
    else:
        return IndicatorAssessment("OIL", value, "crisis", -2, f"Brent ${value:.1f}: 危機水準")


def assess_dollar(value: float) -> IndicatorAssessment:
    """ドル指数の判定

    閾値根拠（1年データ）:
      P25=119.80, P50=120.51, P75=121.29, P90=122.84
      ドル高はレバETF（米国株）に複合的影響
      < 119: weak → 新興国・コモディティにプラス
      119-122: normal
      > 122: strong → 新興国・多国籍企業に逆風
    """
    if value < 119:
        return IndicatorAssessment("USD", value, "weak", 1, f"USD {value:.1f}: ドル安")
    elif value <= 122:
        return IndicatorAssessment("USD", value, "normal", 0, f"USD {value:.1f}: 通常")
    else:
        return IndicatorAssessment("USD", value, "strong", -1, f"USD {value:.1f}: ドル高")


# 指標の重み（レバETF短期トレードへの影響度）
WEIGHTS = {
    "VIX": 2.0,       # 最重要: レバETFはボラに直結
    "VIX_TERM": 1.5,   # ターム構造はレジーム転換の先行指標
    "HY_SPREAD": 1.5,  # クレジットはリスクオフの実体指標
    "YIELD_CURVE": 0.5, # 長期文脈。短期トレードには間接的
    "OIL": 1.0,        # 地政学プロキシ。現局面では重要
    "USD": 0.5,        # 間接的影響
}


def assess_regime(
    vix: Optional[float] = None,
    vix3m: Optional[float] = None,
    hy_spread: Optional[float] = None,
    yield_curve: Optional[float] = None,
    oil: Optional[float] = None,
    usd: Optional[float] = None,
) -> RegimeAssessment:
    """統合レジーム判定

    Charter 3.3 MAP方式: 各指標を独立に評価し、最後に加重平均で統合。
    """
    indicators = []

    if vix is not None:
        indicators.append(assess_vix(vix))
    if vix is not None and vix3m is not None:
        ratio = vix / vix3m
        indicators.append(assess_vix_term_structure(ratio))
    if hy_spread is not None:
        indicators.append(assess_hy_spread(hy_spread))
    if yield_curve is not None:
        indicators.append(assess_yield_curve(yield_curve))
    if oil is not None:
        indicators.append(assess_oil(oil))
    if usd is not None:
        indicators.append(assess_dollar(usd))

    if not indicators:
        return RegimeAssessment("unknown", 0.0, [], "データなし")

    # 加重平均スコア
    total_weight = sum(WEIGHTS.get(ind.name, 1.0) for ind in indicators)
    weighted_score = sum(ind.score * WEIGHTS.get(ind.name, 1.0) for ind in indicators) / total_weight

    # 分類
    if weighted_score > 0.5:
        overall = "risk_on"
    elif weighted_score > -0.5:
        overall = "neutral"
    else:
        overall = "risk_off"

    # 根拠テキスト生成
    parts = [ind.note for ind in indicators]
    reasoning = "。".join(parts)

    return RegimeAssessment(
        overall=overall,
        overall_score=round(weighted_score, 2),
        indicators=indicators,
        reasoning=reasoning,
    )
