---
name: signal-check
description: 確認済みシグナルの発火状況をチェックする。シグナル発火時は[ACTION]で通知し/entry-analysisを提案する。
---

確認済みシグナルの発火チェックを実行してください。

## 前提条件

日足データが最新であること。1日以上古ければ `update_data.py` の実行を先に提案する。

## 実行

```!
python3 << 'PYEOF'
from src.signals import SIGNAL_REGISTRY, check_all_signals
from src.research_utils import load_daily
from src.signal_runner import DEFAULT_DAILY_DIR

results = check_all_signals(lambda sym: load_daily(sym, data_dir=DEFAULT_DAILY_DIR))
for r in results:
    mark = "FIRED" if r.fired else "---"
    print(f"{r.signal_id} {r.symbol}: {mark} ({r.detail})")
PYEOF
```

## 報告フォーマット

発火なし:

```
シグナルチェック完了。発火なし。
```

発火あり:

```
[ACTION] シグナル発火:
- H-18-03: TQQQ 3日連続下落 → ロング推奨
  → /entry-analysis TQQQ long で詳細分析
```
