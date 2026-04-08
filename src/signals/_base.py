"""シグナル定義の基底クラスと判定関数。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd


@dataclass
class SignalDef:
    """1つの確認済みシグナルの定義。"""

    id: str
    name: str
    description: str
    func: Callable[[pd.DataFrame], pd.Series]
    direction: str  # "long" or "short"
    symbols: list[str]
    holding: str = "next_bar"
    status: str = "confirmed"  # "confirmed" / "exploratory"


@dataclass
class SignalResult:
    """1シグナル×1シンボルの判定結果。"""

    signal_id: str
    symbol: str
    fired: bool
    detail: str


def check_signal(
    signal: SignalDef,
    load_fn: Callable[[str], pd.DataFrame],
) -> list[SignalResult]:
    """1つのシグナルを全対象シンボルで判定する。

    Args:
        signal: シグナル定義
        load_fn: シンボル名→DataFrame を返す関数

    Returns:
        シンボルごとのSignalResultリスト
    """
    results = []
    for symbol in signal.symbols:
        try:
            df = load_fn(symbol)
            series = signal.func(df)
            last_value = series.iloc[-1] if len(series) > 0 else None

            if isinstance(last_value, (bool,)):
                fired = bool(last_value)
            elif pd.isna(last_value):
                fired = False
            else:
                fired = bool(last_value)

            results.append(SignalResult(
                signal_id=signal.id,
                symbol=symbol,
                fired=fired,
                detail=f"last_value={last_value}",
            ))
        except Exception as e:
            results.append(SignalResult(
                signal_id=signal.id,
                symbol=symbol,
                fired=False,
                detail=f"error: {e}",
            ))
    return results
