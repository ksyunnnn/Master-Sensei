# ADR-017: フロー評価関数の追加（レジームとの2軸エントリー判断）

Status: accepted
Date: 2026-04-01

## Context

2026-03-31、レジーム判定がrisk_off（スコア-0.5）の環境下でSOXL+17.9%、TQQQ+10.0%の大幅上昇が発生。MAP統合スコアは-4（様子見）と判定し、エントリー機会を捉えられなかった。

原因: レジームは「マクロ背景環境」（VIX水準、HYスプレッド、原油等）を測定するが、「直近の方向と勢い」を測る軸がなかった。risk_off環境でもイベントドリブンの急反転は起きる。

知見K-022として記録済み: 「レジーム（環境）とフロー（勢い）は独立した2軸」。

## Decision

`src/flow.py` に `assess_flow()` を新設する。`regime.py` の `assess_regime()` と同じパターン（IndicatorAssessment + 加重平均 + 閾値分類）を踏襲し、独立したファイルとして実装する。

### フロー指標（4つ）

| 指標 | 入力 | スコア範囲 | 重み |
|------|------|-----------|------|
| PRICE_MOMENTUM | 1日/3日リターン（加重平均） | -2〜+2 | 2.0 |
| VIX_CHANGE | VIX日次変化率 | -2〜+2 | 1.5 |
| VOLUME_SURGE | 出来高/20日平均 × 価格方向 | -2〜+2 | 1.0 |
| SIGMA_POSITION | (Close-SMA20)/σ20 | -2〜+2 | 0.5 |

### 閾値（1年間8銘柄の日足データ分位点）

**PRICE_MOMENTUM:**
- ±7.5%(1d) / ±13%(3d) 超: strong（P95超）
- ±5%(1d) / ±8.5%(3d) 超: bullish/bearish（P90超）
- それ以内: neutral

**VIX_CHANGE:**
- < -12%: sharp_drop（bullish）、> +12%: spiking（bearish）
- ±8%以内: stable（neutral）

**VOLUME_SURGE（方向連動型）:**
- > 1.5x: surge、1.2-1.5x: above_avg、0.7-1.2x: normal、< 0.7x: low
- スコア = magnitude × price_direction（+1/-1/0）

**SIGMA_POSITION:**
- > +2.0 / < -2.0: extreme（P95/P05）
- ±1.0〜±2.0: above/below mean（P25-P75の外）
- ±1.0以内: at_mean

### 設計判断

| 判断 | 選択 | 理由 |
|------|------|------|
| 独立ファイル vs regime.pyに統合 | 独立 | MAP方式（Charter 3.3）。レジームとフローは独立評価→統合 |
| VOLUME_SURGEの方向 | 価格方向連動 | 出来高は増幅器。下落+サージ=bearish conviction |
| 永続化 | しない | 入力データから再計算可能（ADR-003原則） |
| 関数がデータ取得する | しない | 純粋なスコアリング関数。呼び出し側がCacheManagerで値を渡す |

### 統合フロー分類

| フロー | スコア | 意味 |
|--------|--------|------|
| bullish | > +0.5 | 上昇モメンタムが複数指標で確認 |
| neutral | -0.5〜+0.5 | 方向不明 or 混在 |
| bearish | < -0.5 | 下落モメンタムが複数指標で確認 |

## 検証結果

| シナリオ | 期待 | 結果 | フロースコア |
|---------|------|------|------------|
| 3/31 急騰日（SOXL +17.9%） | bullish | bullish | +1.10 |
| 3/30 下落日（SOXL -12.9%） | bearish | bearish | -1.20 |
| 3/27 急落日（SOXL -4.8%） | bearish | bearish | -1.10 |
| 2/20 平穏日 | neutral | neutral | 0.00 |

VOLUME_SURGEの方向バイアス修正前は3/30が-0.80だったが、修正後-1.20に改善。

## Consequences

- エントリー判断時に `assess_regime()` + `assess_flow()` の2軸で提示する
- regime.pyは変更なし
- db.pyのスキーマ変更なし（フローは都度計算）
- 閾値は1年データの分位点に基づく。データ蓄積に伴い見直す
