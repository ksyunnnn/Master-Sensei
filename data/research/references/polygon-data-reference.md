# Polygon.io データ仕様リファレンス

Created: 2026-03-31
Purpose: Polygon.io Starter契約中に取得したデータの仕様記録。解約後の参照用。

## 契約情報

- プラン: Stocks Starter ($29/月)
- 契約日: 2026-03-31
- データ種別: SIP (Securities Information Processor) = 全米取引所合算

## API仕様

### Aggregate Bars (5分足)

**エンドポイント:**
```
GET /v2/aggs/ticker/{ticker}/range/5/minute/{from}/{to}
```

**パラメータ:**
| パラメータ | 値 | 説明 |
|-----------|-----|------|
| adjusted | false | 生データ（スプリット未調整）。ADR-014準拠 |
| limit | 50000 | 1リクエストの最大件数 |

**レスポンスフィールド:**

| フィールド | 型 | 内容 | 単位 |
|-----------|-----|------|------|
| `t` | int | タイムスタンプ | Unix ms (UTC) |
| `o` | float | 始値 | USD |
| `c` | float | 終値 | USD |
| `h` | float | 高値 | USD |
| `l` | float | 安値 | USD |
| `v` | float | 出来高（SIP全取引所合算） | 株数。小数あり（後述） |
| `vw` | float | バー内出来高加重平均価格 | USD |
| `n` | int | バー内取引回数 | 件数 |

### ステータスコード

| status | 意味 |
|--------|------|
| OK | 正常取得 |
| DELAYED | 15分遅延データ（Starterプランの制約。データ自体は取得可能） |
| NOT_AUTHORIZED | プラン外（Starterでは日足のみ過去データ可、インデックスは不可等） |

### Starterプランの制限

| 機能 | 利用可否 |
|------|---------|
| 5分足OHLCV+n+vw | **可** |
| 日足OHLCV | **可** |
| インデックス（I:VIX等） | **不可**（上位プラン要） |
| 個別取引(Trades) | **不可** |
| 気配値(Quotes) | **不可** |
| リアルタイムデータ | 15分遅延（DELAYED） |
| API calls | **無制限** |
| 過去データ | **5年以上**（5分足は2021-04-01〜確認済み） |

## データ特性

### タイムゾーン

- APIレスポンス: Unix ミリ秒 (UTC)
- 変換: `datetime.fromtimestamp(t / 1000, tz=timezone.utc).astimezone(ET)`
- ET = Eastern Time (EDT: UTC-4, EST: UTC-5)

### セッション区分

1日あたり約192バー（銘柄により145-192で変動）:

| セッション | 時間 (ET) | バー数 | 特徴 |
|-----------|----------|--------|------|
| プレマーケット | 04:00-09:25 | ~66 | 流動性低。取引回数はレギュラーの15%程度 |
| レギュラー | 09:30-15:55 | **78** | メイン。Tiingoと一致 |
| アフターマーケット | 16:00-19:55 | ~48 | 決算発表等のリアクション |

### Volume（出来高）の注意点

1. **小数値**: `adjusted=false`でも小数が出る（例: 128119.17）。Polygon公式はadjusted=trueの場合のみと説明するが実態と不一致。原因はおそらくfractional shares。整数丸めで実用上問題なし
2. **SIP vs IEX**: PolygonのvはSIP（全取引所合算）。Tiingo IEXは全体の1-2%のみ
3. **5分足合計 vs 日足**: 5分足Volume合計は日足Volumeの89-97%。差分はオークション・クロージングクロス等の集計方法差
4. **Tiingo日足との比較**: Polygon日足Volume vs Tiingo日足Volume = 比率0.9999-1.0385（ほぼ一致）

### 取引回数 (`n`) の特性

- レギュラーセッション中の日中パターン:
  - 開場直後: ~27,000件/5分（大）
  - 日中: ~5,000-15,000件/5分
  - 引け前15:50-15:55: ~109,000-149,000件/5分（最大。リバランスフロー）
- プレマーケット平均: ~2,500件/5分

### バー内VWAP (`vw`) の特性

- 5分間の出来高加重平均価格
- Close vs VWAPの乖離: 平均-0.014%, 標準偏差0.30%, 最大±1.0-1.2% (SOXL 2026-03-27)
- 日次累積VWAPとは別概念

### 平均取引サイズ (`v/n`) の特性

- 開場直後: ~118株/件
- 引け前: ~32株/件
- 日中で1/4に縮小する傾向（機関→リテールのシフトを反映する可能性）

## 取得対象シンボル

### コア（研究主対象）: 10銘柄

| シンボル | 種別 | 用途 |
|---------|------|------|
| SOXL | 3x Bull半導体 | 主要取引対象 |
| SOXS | 3x Bear半導体 | Bull/Bearペア |
| TQQQ | 3x Bull Nasdaq | 主要取引対象 |
| SQQQ | 3x Bear Nasdaq | Bull/Bearペア |
| TECL | 3x Bull テクノロジー | 主要取引対象 |
| TECS | 3x Bear テクノロジー | Bull/Bearペア（Tiingo 5分足にはなかった） |
| SPXL | 3x Bull S&P 500 | 広範市場 |
| TNA | 3x Bull Russell 2000 | 小型株 |
| TZA | 3x Bear Russell 2000 | Bull/Bearペア |
| VIXY | VIX短期先物 | センチメント（Tiingo 5分足にはなかった） |

### クロスアセット: 8銘柄

| シンボル | 種別 | 用途 |
|---------|------|------|
| SOXX | 半導体ETF（非レバ） | SOX指数代替。トラッキングエラー分析（Cat 6） |
| SPY | S&P 500 ETF | クロスアセット・リード/ラグ（Cat 4, 12） |
| QQQ | Nasdaq 100 ETF | 同上 |
| HYG | ハイイールド債ETF | 日中クレジットストレス（Cat 4, 7）。FRED HY_SPREADは1-2日遅延 |
| TLT | 20年超国債ETF | 金利の日中変動プロキシ（Cat 4） |
| USO | 原油ETF | Brentの日中プロキシ（Cat 4） |
| UUP | ドルインデックスETF | USD_INDEXの日中プロキシ（Cat 4） |
| IWM | Russell 2000 ETF（非レバ） | 小型株ベンチマーク |

## 保存仕様

- 保存先: `data/research/polygon_intraday/{SYMBOL}_5min.parquet`
- カラム: Open, High, Low, Close, Volume, VWAP, NumTrades
- index: datetime (tz=America/New_York)
- adjusted=false（生データ）。ADR-014に従いスプリット調整は読み込み時
- 全セッション含む（プレマーケット+レギュラー+アフター）
- 取得期間: 2021-04-01 ~ 2026-03-30

## Tiingoとの比較

| 観点 | Tiingo IEX | Polygon SIP |
|------|-----------|-------------|
| Volume | IEXのみ（全体の1-2%） | 全取引所合算（SIP） |
| 取引回数(n) | なし | あり |
| バー内VWAP(vw) | なし | あり |
| 拡張時間帯 | なし（レギュラーのみ） | あり（プレ+アフター） |
| 価格精度 | 基準 | 平均差$0.005（実質同一） |
| 過去データ | Tiingoプランに依存 | 5年以上 |
| コスト | 無料（IEX） | $29/月（Starter） |
| スプリット調整 | 未調整（生データ） | 未調整（adjusted=false） |
