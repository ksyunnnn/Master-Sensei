# ADR-002: データソース選定

Status: accepted
Date: 2026-03-26

## Context

Master Senseiが総合アドバイザーとして機能するために、どのデータソースを採用するか決定する。
既存のfeasibility_study/macroではFRED（4シリーズ）とTiingo（OHLCV）を使用中。
独立ディレクトリとして再構築するにあたり、最適なデータセットを選定する。

## Options

### API: FRED（Federal Reserve Economic Data）

無料。既にAPIキーあり。公式: https://fred.stlouisfed.org

#### 採用するシリーズ

| Series ID | 名称 | 更新頻度 | 採否 | 理由 |
|-----------|------|---------|------|------|
| VIXCLS | CBOE VIX | 日次 | **採用** | ボラティリティの基本指標。レジーム判定の核 |
| VXVCLS | CBOE S&P 500 3-Month Volatility | 日次 | **採用** | VIX3M相当。VIXCLS/VXVCLSでターム構造（コンタンゴ/バックワーデーション）判定 |
| VXNCLS | CBOE Nasdaq 100 Volatility | 日次 | **採用** | TQQQ/SOXL/TECLはNasdaq寄りのため、VXNの方が直接的 |
| DCOILBRENTEU | Brent原油 | 日次 | **採用** | 地政学リスクのプロキシ |
| DGS10 | 米国10年国債利回り | 日次 | **採用** | 金利環境の基本指標 |
| FEDFUNDS | FF金利 | 月次 | **採用** | 金融政策スタンスの把握 |
| T10Y2Y | 10年-2年スプレッド | 日次 | **採用** | イールドカーブ。逆転は景気後退シグナル |
| T10Y3M | 10年-3M スプレッド | 日次 | **見送り** | T10Y2Yと高相関。最小限の原則に反する |
| BAMLH0A0HYM2 | HYスプレッド | 日次 | **採用** | クレジットストレスの直接指標。リスクオフ検出に有効 |
| DTWEXBGS | ドル指数 | 日次 | **採用** | ドル高は新興国・コモディティに影響。レバETFの外部環境 |

**合計: 9シリーズ**（既存4 + 新規5）

#### 見送るシリーズ

| Series ID | 名称 | 見送り理由 | 再検討トリガー |
|-----------|------|-----------|---------------|
| T10Y3M | 10年-3M スプレッド | T10Y2Yと高相関、冗長 | T10Y2Yでは捉えられない現象が出たとき |
| CPILFESL | コアCPI | 月次で遅行。短期トレードには粒度不足 | スイングトレードに拡大する場合 |
| UNRATE | 失業率 | 同上 | 同上 |
| SKEW | CBOE SKEW | FREDに存在しない。別途CBOE直接取得が必要でAPI管理コスト増 | 無料APIが見つかった場合 |

### API: Tiingo

有料（Power $30/mo利用中想定）。公式: https://www.tiingo.com/documentation

| データ | エンドポイント | 採否 | 理由 |
|--------|-------------|------|------|
| 日足OHLCV | /tiingo/daily/{symbol}/prices | **採用** | レバETF価格データの基盤 |
| 5分足OHLCV | /iex/{symbol}/prices | **採用** | イントラデイ分析用 |
| Crypto | /tiingo/crypto/prices | **見送り** | スコープ外（米国レバETF特化） |
| News | /tiingo/news | **見送り** | テキスト分析の仕組みが未構築 |

#### 対象シンボル

| Symbol | 種別 | 理由 |
|--------|------|------|
| TQQQ | 取引対象 | Nasdaq100 3x Bull |
| SOXL | 取引対象 | 半導体 3x Bull |
| TECL | 取引対象 | テクノロジー 3x Bull |
| SPXL | 取引対象 | S&P500 3x Bull |
| SOXS | ヘッジ参考 | 半導体 3x Bear |
| VIXY | 参考指標 | VIX短期先物ETF |

### 見送るAPI/データソース

| ソース | 見送り理由 | 再検討トリガー |
|--------|-----------|---------------|
| CNN Fear & Greed | 公式APIなし。スクレイピング必要で脆弱 | 公式API提供時 |
| AAII Sentiment | 有料($50/年)、週次で粒度不足 | 無料化時 |
| Put/Call Ratio | FREDにない。CBOE直接取得が必要 | 無料APIが見つかった場合 |
| 経済カレンダー | 構造化APIが限定的 | 信頼性の高い無料API発見時 |

## Decision

> **FRED 9シリーズ + Tiingo 6シンボル（日足+5分足）を採用する。**
> 新規追加はVXVCLS, VXNCLS, T10Y2Y, BAMLH0A0HYM2, DTWEXBGSの5シリーズ。
> 最小限の原則に基づき、高相関な指標の重複を避ける。

## Rationale

- すべて公式API経由。スクレイピングや非公式ソースは採用しない
- FRED APIは無料で安定稼働実績あり（既存macroシステムで実証済み）
- 新規5シリーズの選定基準: 既存指標と低相関かつレバETFトレード判断に直接寄与
  - VXVCLS: VIXターム構造はレジーム転換の先行指標
  - VXNCLS: Nasdaq系レバETFにはVXNの方がVIXより直接的
  - T10Y2Y: 景気サイクルの長期文脈
  - BAMLH0A0HYM2: クレジットストレスはリスクオフの実体指標
  - DTWEXBGS: ドル環境は新興国・コモディティ経由でテック株に波及

## Consequences

- src/fred_client.pyにSERIES_CONFIGとして9シリーズを定義
- data/parquet/macro/配下にシリーズ別Parquetファイルを保存
- VIXターム構造比率（VIXCLS/VXVCLS）はレジーム判定で使用
- 再検討: 四半期レビュー時に「見送り」シリーズの再評価を行う
