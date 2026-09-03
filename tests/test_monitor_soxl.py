"""scripts/monitor_soxl.py の純粋ロジック (classify / pct_from) のテスト。

I/O (yfinance polling, terminal-notifier) はテスト対象外。
当日値に依存しない signal 判定ロジックのみを検証する。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.monitor_soxl import MonitorConfig, classify, pct_from, should_notify


def _cfg(**overrides) -> MonitorConfig:
    base = dict(
        symbol="SOXL",
        reference="SOXX",
        leverage=3.0,
        long_dip=[210.0, 205.0, 200.0],
        short_rally=[230.0, 235.0],
        fill_tolerance=1.5,
        reversal_pct=1.5,
        vol_flag_pct=3.0,
        sox_divergence=2.0,
        driver_retrace_pct=3.0,
        lead_flip_pct=-1.5,
        ref_rebound_pct=1.5,
    )
    base.update(overrides)
    return MonitorConfig(**base)


def _classify(price, *, pct=None, ref_pct=None, lead_pct=None,
              retrace_driver_pct=None, retrace_driver_high_pct=None,
              session_high=None, session_low=None, cfg=None):
    """テスト用ヘルパ: session high/low 未指定なら price と同値。"""
    return classify(
        price=price,
        pct=pct,
        ref_pct=ref_pct,
        lead_pct=lead_pct,
        retrace_driver_pct=retrace_driver_pct,
        retrace_driver_high_pct=retrace_driver_high_pct,
        session_high=session_high if session_high is not None else price,
        session_low=session_low if session_low is not None else price,
        cfg=cfg or _cfg(),
    )


def test_pct_from():
    assert pct_from(110.0, 100.0) == pytest.approx(10.0)
    assert pct_from(90.0, 100.0) == pytest.approx(-10.0)
    assert pct_from(None, 100.0) is None
    assert pct_from(100.0, None) is None
    assert pct_from(100.0, 0.0) is None  # ゼロ除算回避


def test_reversal_up_requires_lead_confirmation():
    # session low $200 から +2% bounce、lead driver (NVDA) プラス → REVERSAL UP 発火
    state, code = _classify(204.0, session_low=200.0, session_high=204.0, lead_pct=0.3)
    assert code is not None
    assert code.startswith("REVERSAL_UP")
    assert "REVERSAL UP" in state

    # 同じ bounce でも lead driver マイナス → 発火しない (false positive 抑止)
    state2, code2 = _classify(204.0, session_low=200.0, session_high=204.0, lead_pct=-0.3)
    assert code2 != f"REVERSAL_UP_FROM_{200}"
    assert (code2 is None) or (not code2.startswith("REVERSAL_UP"))


def test_reversal_down_requires_lead_breakdown():
    # session high $230 から -2% drop、lead driver 崩壊 (<= -0.5%) → REVERSAL DOWN
    state, code = _classify(225.0, session_high=230.0, session_low=225.0, lead_pct=-0.8)
    assert code is not None and code.startswith("REVERSAL_DOWN")

    # lead driver がまだ堅調 → 発火しない
    _, code2 = _classify(225.0, session_high=230.0, session_low=225.0, lead_pct=0.2)
    assert (code2 is None) or (not code2.startswith("REVERSAL_DOWN"))


def test_long_dip_fill_zone():
    state, code = _classify(205.4)  # $205 zone から ±1.5 以内
    assert code == "LONG_DIP_205"
    assert "205" in state


def test_short_rally_fill_zone():
    _, code = _classify(229.5)  # $230 zone 近傍
    assert code == "SHORT_RALLY_230"


def test_intraday_vol_flag():
    # range $200-$210 = 5% (>3% flag)、ただし価格は zone から離す
    _, code = _classify(216.0, session_low=200.0, session_high=216.0)
    assert code is not None and code.startswith("VOL_FLAG")


def test_sox_divergence_underperform():
    # SOXL +2%、SOXX +2% (期待 +6%)、spread -4% < -2% → underperform (bounce 機会)
    _, code = _classify(216.0, pct=2.0, ref_pct=2.0)
    assert code == "SOXL_UNDER"


def test_sox_divergence_overperform():
    # SOXL +10%、SOXX +2% (期待 +6%)、spread +4% > +2% → overperform (decay リスク)
    _, code = _classify(216.0, pct=10.0, ref_pct=2.0)
    assert code == "SOXL_OVER"


def test_driver_retrace_warning():
    # retrace driver (MU) が高値 +5% から現在 +1% = 4% 戻り (>3%) → MU_REVERSAL
    _, code = _classify(216.0, retrace_driver_pct=1.0, retrace_driver_high_pct=5.0)
    assert code == "MU_REVERSAL"


def test_deep_dip_below_lowest_zone():
    # 最安 dip zone $200 を fill_tolerance 超で下回る → DEEP_DIP
    _, code = _classify(195.0, session_low=195.0, session_high=195.0)
    assert code == "DEEP_DIP"


def test_gap_fill_above_highest_zone():
    _, code = _classify(240.0, session_low=240.0, session_high=240.0)
    assert code == "GAP_FILL"


def test_normal_observation_no_trigger():
    # zone 外・連動 fair・rebound/flip 閾値未満の中間価格 → trigger なし
    # SOXL +3% / SOXX +1% (期待 +3%、spread 0)、ref +1% < rebound 1.5%
    _, code = _classify(220.0, pct=3.0, ref_pct=1.0)
    assert code is None


def test_reversal_up_lead_min_is_configurable():
    """lead driver がマイナスのまま反発する局面でも REVERSAL UP を拾えること。

    セクター全体が売られている日は lead driver (NVDA) がプラスに戻る前に
    レバ ETF が底打ちする。既定の `reversal_lead_min=0.0` だと反転を一度も
    通知できず、監視が「下げだけ報告して底を報告しない」非対称になる
    (2026-09-01 の SOXL 下落で実際に発生)。
    """
    # 既定 (0.0) では lead driver -2.2% なので発火しない = 従来挙動の固定
    _, code_default = _classify(
        204.0, session_low=200.0, session_high=204.0, lead_pct=-2.2
    )
    assert (code_default is None) or (not code_default.startswith("REVERSAL_UP"))

    # 閾値を -3.0% まで緩めれば同じ入力で発火する
    cfg = _cfg(reversal_lead_min=-3.0)
    state, code = _classify(
        204.0, session_low=200.0, session_high=204.0, lead_pct=-2.2, cfg=cfg
    )
    assert code is not None and code.startswith("REVERSAL_UP")
    assert "REVERSAL UP" in state

    # 緩めても閾値より下 (leadership が完全崩壊) なら発火しない
    _, code_deep = _classify(
        204.0, session_low=200.0, session_high=204.0, lead_pct=-4.5, cfg=cfg
    )
    assert (code_deep is None) or (not code_deep.startswith("REVERSAL_UP"))


# ── notify dedup ─────────────────────────────────────────

def test_should_notify_suppresses_repeat_of_same_code():
    """一度通知した trigger code は、間に通常観測を挟んでも再通知しない。

    zone 判定は `abs(price - zone) <= fill_tolerance` の帯なので、価格が帯の
    境界に留まると「帯の中→外→中」を繰り返す。旧実装の dedup は直前の
    action と比較するだけだったため、帯を一度出るたびに last_action が None に
    戻り、同じ SHORT_RALLY_106 が何度も通知された
    (2026-09-03 の SOXL 監視で $104.50 境界にて実際に発生)。

    再発火してよい trigger は code 自体に水準を埋め込んでいる
    (REVERSAL_UP_FROM_100 と REVERSAL_UP_FROM_98 は別 code) ため、
    code 単位で一度きりに固定してよい。
    """
    fired: set[str] = set()

    assert should_notify("SHORT_RALLY_106", fired) is True
    fired.add("SHORT_RALLY_106")

    # 通常観測 (action=None) を挟んでも None は通知しない
    assert should_notify(None, fired) is False

    # 帯に戻ってきても再通知しない
    assert should_notify("SHORT_RALLY_106", fired) is False

    # 別の水準の code は独立して通知される
    assert should_notify("LONG_DIP_98", fired) is True


def test_should_notify_distinguishes_reversal_levels():
    """安値を切り下げた reversal は別 code なので通知される。"""
    fired = {"REVERSAL_UP_FROM_100"}
    assert should_notify("REVERSAL_UP_FROM_100", fired) is False
    assert should_notify("REVERSAL_UP_FROM_98", fired) is True
