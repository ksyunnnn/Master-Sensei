"""H-18-03: 3日連続下落→翌日ロング

Status: confirmed (2026-04-06)
Evidence:
  - TQQQ 64.8%, TECL 64.2%, TZA 58.7%
  - CSCV 70/70 OOS正リターン
  - 摩擦後+1.42%/回（TQQQ）
  - Walk-forward, レジーム安定性, shuffle全通過
"""
from src.signal_defs import h_18_03
from src.signals._base import SignalDef

signal = SignalDef(
    id="H-18-03",
    name="連続3日下落→ロング",
    description="3営業日連続で終値が前日比マイナスなら翌日ロング",
    func=h_18_03,
    direction="long",
    symbols=["TQQQ", "TECL"],
    holding="next_bar",
    status="confirmed",
)
