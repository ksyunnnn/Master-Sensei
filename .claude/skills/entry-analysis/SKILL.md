---
name: entry-analysis
description: 銘柄・方向を指定してMAP分析→シナリオ別注文設定→trade記録まで実行する。後知恵バイアス排除のため、分析結果をエントリー時点で自動記録する。
---

エントリー分析を実行してください。

## 引数

ユーザーが `/entry-analysis SOXL long` のように銘柄と方向を指定する。
指定がない場合は「どの銘柄にどの方向で入りたいですか？」と確認する。

## タイムゾーン

現在時刻(JST): !`python3 -c "from datetime import datetime, timezone, timedelta; jst=timezone(timedelta(hours=9)); print(datetime.now(tz=jst).strftime('%Y-%m-%d %H:%M JST'))"`

## 手順

### 1. データ鮮度チェック

```bash
python << 'PYEOF'
from pathlib import Path
from src.cache_manager import CacheManager

cache = CacheManager(Path("data/parquet"))
meta = cache.get_all_metadata()

# 日足の最新日
for symbol in ["SOXL", "TQQQ", "TECL", "SPXL"]:
    m = meta["daily"].get(symbol)
    if m:
        print(f"  {symbol} daily: {m['end_date']}")

# マクロの最新日
for series in ["VIX", "VIX3M", "HY_SPREAD", "BRENT"]:
    m = meta["macro"].get(series)
    if m:
        print(f"  {series}: {m['end_date']}")
PYEOF
```

- 日足またはマクロが1日以上古い場合 → `update_data.py` の実行を提案（P2: 警告して続行）

### 2. MAP分析（3軸独立評価）

Charter 3.3: 各軸を独立に評価してから統合する。先に結論を出さない。

#### Axis 1: Regime（環境）

```bash
python << 'PYEOF'
from pathlib import Path
from src.cache_manager import CacheManager
from src.regime import assess_regime

cache = CacheManager(Path("data/parquet"))
series_names = ["VIX", "VIX3M", "HY_SPREAD", "YIELD_CURVE", "BRENT", "USD_INDEX"]
values = {}
for name in series_names:
    df = cache.load_macro(name)
    if not df.empty:
        values[name] = float(df["value"].iloc[-1])

regime = assess_regime(
    vix=values.get("VIX"),
    vix3m=values.get("VIX3M"),
    hy_spread=values.get("HY_SPREAD"),
    yield_curve=values.get("YIELD_CURVE"),
    oil=values.get("BRENT"),
    usd=values.get("USD_INDEX"),
)
print(f"Regime: {regime.overall} ({regime.overall_score:+.2f})")
print(f"  {regime.reasoning}")
for ind in regime.indicators:
    print(f"  {ind.name}: {ind.value:.2f} -> {ind.regime} (score={ind.score})")
PYEOF
```

#### Axis 2: Flow（勢い）

```bash
python << 'PYEOF'
from pathlib import Path
from src.cache_manager import CacheManager
from src.flow import assess_flow, compute_flow_inputs

cache = CacheManager(Path("data/parquet"))

# 対象銘柄の日足とVIXを取得
SYMBOL = "{対象銘柄}"
daily_df = cache.load_daily(SYMBOL)
vix_df = cache.load_macro("VIX")

# Parquetから自動計算
inputs = compute_flow_inputs(daily_df, vix_df)
print("Flow inputs:")
for k, v in inputs.items():
    if v is not None:
        print(f"  {k}: {v:.4f}")
    else:
        print(f"  {k}: None")

flow = assess_flow(symbol=SYMBOL, **inputs)
print(f"\nFlow: {flow.overall} ({flow.overall_score:+.2f})")
print(f"  {flow.reasoning}")
PYEOF
```

#### Axis 3: Event Risk（直近イベント）

```bash
python << 'PYEOF'
import duckdb
from src.db import SenseiDB
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)

# 今後7日のイベントを取得
events = db.get_active_events()
print(f"Active events: {len(events)}件")
# 直近7日のものをフィルタして表示
from datetime import datetime, timedelta
from src.db import JST
now = datetime.now(tz=JST)
upcoming = [e for e in events
            if e["event_timestamp"] >= now - timedelta(days=1)
            and e["event_timestamp"] <= now + timedelta(days=7)]
print(f"今後7日: {len(upcoming)}件")
for e in upcoming[:10]:
    print(f"  [{e['category']}] {e['event_timestamp'].strftime('%m/%d %H:%M')} {e['summary'][:60]}")

conn.close()
PYEOF
```

#### 補足情報: 関連知見・注文制約・既存予測

**重要**: instrument カテゴリ知見（取引所・ブローカー制約）は注文設計に直結するため、常に全件表示する。市場分析系知見（market/meta/signal 等）は上位8件に絞る。

```bash
python << 'PYEOF'
import duckdb
from src.db import SenseiDB
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)

knowledge = db.get_active_knowledge()

# instrument カテゴリ（注文制約）は全件表示 — 同日反転可否等、注文設計に直結
instrument_k = [k for k in knowledge if k.get('category') == 'instrument']
print(f"=== 注文制約知見 ({len(instrument_k)}件) ===")
for k in instrument_k:
    kid = k.get('id')
    tldr = k.get('tldr') or (k.get('content', '')[:100])
    print(f"  {kid}: {tldr}")

# その他カテゴリは上位8件
other_k = [k for k in knowledge if k.get('category') != 'instrument']
print(f"\n=== 関連知見 ({len(other_k)}件中 上位8件) ===")
for k in other_k[:8]:
    kid = k.get('id')
    cat = k.get('category', '')
    tldr = k.get('tldr') or (k.get('content', '')[:70])
    print(f"  {kid} [{cat}]: {tldr}")

# 対象銘柄の未解決予測
predictions = db.get_pending_predictions()
print(f"\n=== 未解決予測 ({len(predictions)}件) ===")
for p in predictions:
    print(f"  #{p['id']} {p['subject'][:60]} (conf={p['confidence']}, deadline={p['deadline']})")

conn.close()
PYEOF
```

### 3. TP/SLの統計的根拠を計算

```bash
python << 'PYEOF'
from pathlib import Path
import numpy as np
from src.cache_manager import CacheManager

cache = CacheManager(Path("data/parquet"))
SYMBOL = "{対象銘柄}"
df = cache.load_daily(SYMBOL)

if len(df) >= 20:
    closes = df["Close"]
    sma20 = closes.iloc[-20:].mean()
    std20 = closes.iloc[-20:].std()
    last_close = closes.iloc[-1]

    print(f"=== {SYMBOL} テクニカル ===")
    print(f"  前日終値: ${last_close:.2f}")
    print(f"  SMA20:    ${sma20:.2f}")
    print(f"  20日 sigma: ${std20:.2f}")
    print(f"  sigma位置: {(last_close - sma20) / std20:+.2f}")
    print()
    print(f"  +1.0 sigma: ${sma20 + std20:.2f} ({(sma20 + std20 - last_close) / last_close:+.1%})")
    print(f"  +1.5 sigma: ${sma20 + 1.5*std20:.2f} ({(sma20 + 1.5*std20 - last_close) / last_close:+.1%})")
    print(f"  +2.0 sigma: ${sma20 + 2*std20:.2f} ({(sma20 + 2*std20 - last_close) / last_close:+.1%})")
    print(f"  -1.0 sigma: ${sma20 - std20:.2f} ({(sma20 - std20 - last_close) / last_close:+.1%})")
    print(f"  -1.5 sigma: ${sma20 - 1.5*std20:.2f} ({(sma20 - 1.5*std20 - last_close) / last_close:+.1%})")

    # 直近20日のリターン分布
    daily_returns = closes.pct_change().dropna().iloc[-60:]
    print(f"\n  日次リターン分布（直近60日）:")
    for pct in [10, 25, 50, 75, 90]:
        print(f"    P{pct}: {np.percentile(daily_returns, pct):+.1%}")
PYEOF
```

### 3.5 ポジションサイズ算出（risk-based, ADR-028）

数量は直感で決めず risk-based で逆算する。**投入割合 = risk% ÷ stop距離%**。

1. **stop（無効化ライン）を先に決める**: 手順3のσ/サポレジから「ここを割れたら読みが外れ」の価格。stop幅$ = エントリー − stop価格。
2. **risk%**: 基準 **4%**（ADR-028）、確信度（MAP）で下方スケール（低確信なら3%等）。
3. **株数 = floor((余力USD × risk%) ÷ stop幅$)**。cap ~90% を超えたら削る。
4. add は実MAE −3〜5% に置き、残弾を2発目 tranche として確保。「割合◯%入れたい」から逆算して stop を置くのは禁止。

```bash
python << 'PYEOF'
# risk-based サイジング (ADR-028)
EQUITY_USD = 0.0   # Saxo spending_power (T126816 等、余力USD)
RISK_PCT = 0.04    # 基準4%、確信度で下げる
ENTRY = 0.0        # エントリー価格
STOP = 0.0         # 無効化ライン (手順3のサポレジ/σ から)
CAP = 0.90

stop_dist = ENTRY - STOP
risk_usd = EQUITY_USD * RISK_PCT
shares = int(risk_usd // stop_dist) if stop_dist > 0 else 0
while shares > 0 and shares * ENTRY > EQUITY_USD * CAP:
    shares -= 1
deploy = shares * ENTRY / EQUITY_USD if EQUITY_USD else 0
eff_risk = shares * stop_dist / EQUITY_USD if EQUITY_USD else 0
print(f"stop幅 ${stop_dist:.2f} ({stop_dist/ENTRY:.1%})")
print(f"risk予算 ${risk_usd:.0f} ({RISK_PCT:.0%})")
print(f"株数 {shares}株 (${shares*ENTRY:.0f}, 投入{deploy:.0%}), 実効risk {eff_risk:.1%}")
PYEOF
```

ラダー時は first/add の2 tranche に risk% を配分し、合計が基準 risk% に収まるようにする。

### 4. シナリオ別注文設定の提示

手順2-3の結果を統合し、以下のフォーマットで提示する。

**重要: シナリオはテンプレート固定しない。** イベント・レジーム・フローから動的に構築する。
地政学危機時は「エスカレ/膠着/沈静化」、通常市場時は「上昇継続/レンジ/調整」など、
状況に応じた2-3シナリオを構築すること。

**注文制約の反映（instrument知見）**: 手順2の「注文制約知見」セクションで取得した
instrument カテゴリ知見を注文設計に必ず反映する。特に以下を確認:
- 同日反転ポジション（同一銘柄long→short等）を計画するシナリオは、Saxoのwash trading
  防止規制（K-031）に抵触するため不可。回避策は (a)別銘柄で代替 (b)翌営業日 (c)事前原資確保
- 反転を要するシナリオが存在する場合、シナリオ名にそれを明示し、注文設計段階で代替手段
  を選択する（例: 「SOXL TP到達→SOXS買い」ではなく「SOXL TP到達→部分利確+翌日SOXS」）

```
=== /entry-analysis {銘柄} {方向} ===
{日時 JST}

[環境] {regime.overall} ({regime.overall_score:+.2f}) | {主要指標のサマリー}
[フロー] {flow.overall} ({flow.overall_score:+.2f}) | {主要指標のサマリー}
[イベント] {N}件(7日以内): {主要イベント列挙}
[関連知見] {関連知見のID+要約}

--- シナリオ別 注文設定 ---

| | A: {シナリオA名} | B: {シナリオB名} | C: {シナリオC名} |
|---|---|---|---|
| 確率 | {X}% | {Y}% | {Z}% |
| {銘柄}方向 | {想定値動き} | {想定値動き} | {想定値動き} |

{ユーザーの方向が合理的なシナリオに基づく注文設定}:

| 項目 | 値 | 根拠 |
|---|---|---|
| エントリー | {指値/成行} ${価格} | {前日終値比/サポレジ根拠} |
| TP(利確) | ${価格} ({+X%}) | {σ水準/シナリオ根拠} |
| SL(損切) | ${価格} ({-X%}) | {σ水準/SMA根拠} |
| 数量 | {N}株 (${金額}, 投入{X}%) | risk-based: risk{R}% ÷ stop{S}% (手順3.5, ADR-028) |

--- Confidence ---
A) {低め}% — {根拠}
B) {中間}% — {根拠}
C) {高め}% — {根拠}
```

### 5. ユーザー確認 → trade記録

ユーザーがconfidenceを選択し、注文内容を確認したら、add_trade()を実行する。

```bash
python << 'PYEOF'
import duckdb
from datetime import date
from src.db import SenseiDB, today_jst
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)

tid = db.add_trade(
    instrument="{銘柄}",
    direction="{long/short}",
    entry_date=today_jst(),
    entry_price={エントリー価格},
    quantity={数量},
    regime_at_entry="{regime.overall}",
    vix_at_entry={VIX値},
    brent_at_entry={Brent値},
    confidence_at_entry={confidence/100},
    setup_type="{シナリオから導出}",
    entry_reasoning=(
        "[環境] {regime.overall} ({regime.overall_score:+.2f}). "
        "[フロー] {flow.overall} ({flow.overall_score:+.2f}). "
        "[イベント] {イベントサマリー}. "
        "[シナリオ] {選択したシナリオの要約}. "
        "[注文] entry=${entry} TP=${tp} SL=${sl}"
    ),
    status="{placed/filled}",  # ADR-027: 即時約定なら filled(既定)、resting指値/IFD-OCOは placed
)
print(f"Trade #{tid} recorded")
conn.close()
PYEOF
```

### 6. 実行記録

```bash
python << 'PYEOF'
import json
from datetime import datetime
import duckdb
from src.db import SenseiDB, JST
conn = duckdb.connect('data/sensei.duckdb')
db = SenseiDB(conn)
db.record_skill_execution(
    skill_name='entry-analysis',
    executed_at=datetime.now(tz=JST),
    result_summary='{銘柄} {方向} — trade #{tid} recorded, confidence {X}%',
    metadata=json.dumps({
        'symbol': '{銘柄}',
        'direction': '{方向}',
        'regime': '{regime.overall}',
        'flow': '{flow.overall}',
        'trade_id': {tid},
    }),
)
conn.close()
PYEOF
```

## 注意事項

- SQLは直接書かず、SenseiDBのメソッドを使用する（ADR-008）
- entry_reasoningはエントリー時点の分析を記録する。事後に書き換えない（ADR-003 Decision Tracking）
- シナリオ構築はテンプレート固定しない。状況に応じて動的に構築する
- TP/SLは日足のσ・SMAから統計的根拠を計算する。「なんとなく+10%/-5%」は禁止
- **数量は risk-based で逆算する（手順3.5, ADR-028）。直感で決めない**。stopをチャートから読み、株数 = (余力 × 基準risk4%) ÷ stop幅$。「割合◯%入れたい」からstopを逆算するのは禁止
- heredoc内でトリプルクォート禁止（グローバルCLAUDE.md）
- {対象銘柄} のプレースホルダーは実行時にユーザー指定の銘柄に置き換える
- ユーザーがtrade記録を希望しない場合（分析だけ見たい場合）はadd_trade()をスキップ可
- ADR-027: resting指値/IFD-OCOを発注時点で記録する場合は `status="placed"` を渡す。約定確認後に `update_trade_status(tid, "filled")`、不発キャンセル時は `update_trade_status(tid, "cancelled", notes=...)`。物理削除はしない（発注=意思決定の事実を残す）
