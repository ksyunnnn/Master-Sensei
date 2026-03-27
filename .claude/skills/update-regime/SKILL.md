---
name: update-regime
description: yfinanceで最新のVIX/VIX3M/Brent/ドル指数を取得し、レジーム再判定を行ってDBに記録する
---

レジーム更新ワークフローを実行してください。

## 手順

1. yfinanceで最新値を取得する:
   ```python
   import yfinance as yf
   tickers = {"^VIX": "VIX", "^VIX3M": "VIX3M", "BZ=F": "Brent", "DX-Y.NYB": "DXY"}
   for symbol, name in tickers.items():
       data = yf.Ticker(symbol).history(period="1d")
       # 最新のClose値を表示
   ```

2. FRED系列の最新値をParquetから取得する（HYスプレッド、イールドカーブ等）:
   ```python
   import duckdb
   conn = duckdb.connect("data/sensei.duckdb")
   # read_parquet() でマクロParquetから最新値を取得
   ```

3. `src/assess_regime.py` のレジーム判定ロジックを使って各指標を判定する。

4. 結果をユーザーに提示し、確認を得る。

5. 確認後、`SenseiDB` を使って記録する:
   ```python
   from src.db import SenseiDB
   db = SenseiDB(conn)
   db.save_regime(date.today(), vix_regime=..., overall=..., reasoning=...)
   ```

6. 取得した最新値を `market_observations` にも記録する（source明記必須）:
   ```python
   db.add_observation(date.today(), "VIX", value, "yfinance", observed_at)
   ```

## 注意事項

- yfinanceのデータは非公式。sourceは必ず `"yfinance"` と記録する（ADR-006）
- 前日と変化がない場合はregime_assessmentsへの記録は不要（ADR-003）
- SQLは直接書かず、SenseiDBのメソッドを使用する（ADR-008）
