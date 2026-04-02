---
name: update-regime
description: Parquetから最新マクロデータを読み取り、レジーム再判定を行ってDBに入力値スナップショット付きで記録する
---

レジーム更新ワークフローを実行してください。

## タイムゾーン

現在時刻(JST): !`python3 -c "from datetime import datetime, timezone, timedelta; jst=timezone(timedelta(hours=9)); print(datetime.now(tz=jst).strftime('%Y-%m-%d %H:%M JST'))"`

## 手順

1. まず `update_data.py --macro-only` を実行��てParquetを最新化する:
   ```bash
   python update_data.py --macro-only
   ```

2. Parquetから最新値を取得する:
   ```python
   from src.cache_manager import CacheManager
   from pathlib import Path
   cache = CacheManager(Path("data/parquet"))

   series_names = ["VIX", "VIX3M", "HY_SPREAD", "YIELD_CURVE", "BRENT", "USD_INDEX"]
   values = {}
   for name in series_names:
       df = cache.load_macro(name)
       if not df.empty:
           values[name] = float(df["value"].iloc[-1])
   ```

3. `src/regime.py` のレジーム判定ロジックで各指標を判定する:
   ```python
   from src.regime import assess_regime
   result = assess_regime(
       vix=values.get("VIX"),
       vix3m=values.get("VIX3M"),
       hy_spread=values.get("HY_SPREAD"),
       yield_curve=values.get("YIELD_CURVE"),
       oil=values.get("BRENT"),
       usd=values.get("USD_INDEX"),
   )
   ```

4. 結果をユーザーに��示し、確認を得る。

5. 確認後、`SenseiDB` を使って入力値スナップショット付きで記録する（ADR-009）:
   ```python
   from src.db import SenseiDB, today_jst
   db = SenseiDB(conn)
   db.save_regime(
       today_jst(),
       vix_regime=...,
       overall=...,
       reasoning=...,
       vix_value=values.get("VIX"),
       vix3m_value=values.get("VIX3M"),
       hy_spread_value=values.get("HY_SPREAD"),
       yield_curve_value=values.get("YIELD_CURVE"),
       oil_value=values.get("BRENT"),
       usd_value=values.get("USD_INDEX"),
   )
   ```

## 注意事項

- 前日と変化がない場合はregime_assessmentsへの記録は不要（ADR-003）
- SQLは直接書かず、SenseiDBのメソッドを使用する（ADR-008）
- 入力値スナップショットは必須。省略しない（ADR-009）
- Parquetデータが古い場合は `update_data.py` の実行を先に促す
