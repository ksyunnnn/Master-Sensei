"""シグナルレジストリ。signals/配下のモジュールを自動走査して登録する。"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from src.signals._base import SignalDef, SignalResult, check_signal

SIGNAL_REGISTRY: list[SignalDef] = []


def _discover_signals() -> None:
    """signals/配下の全モジュールから`signal`属性を収集する。"""
    package_dir = Path(__file__).parent
    for info in pkgutil.iter_modules([str(package_dir)]):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"src.signals.{info.name}")
        if hasattr(module, "signal"):
            sig = getattr(module, "signal")
            if isinstance(sig, SignalDef):
                SIGNAL_REGISTRY.append(sig)


_discover_signals()


def check_all_signals(
    load_fn,
) -> list[SignalResult]:
    """全登録シグナルを判定する。"""
    results = []
    for sig in SIGNAL_REGISTRY:
        results.extend(check_signal(sig, load_fn))
    return results


__all__ = ["SIGNAL_REGISTRY", "SignalDef", "SignalResult", "check_signal", "check_all_signals"]
