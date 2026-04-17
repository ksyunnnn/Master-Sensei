# Curriculum: Master Sensei 読解のための金融・投資スキーマ構築

Last updated: 2026-04-16

## 診断基準日

2026-04-16 診断結果:
- A (自分の言葉で 2 文説明可): ADR, SL/TP+OCO
- B (直感あり、tightening 必要): ETF, 平均回帰, 3x レバレッジ, Decay, regime_assessments
- C (未知): VIX, MAP, EPS, コンタンゴ/バックワーデーション, σ/SMA20, イールドカーブ, NII, ガイダンス, BE SL, K-XXX 番号意味, Section 232

## Stage 設計

4 Stage 段階、各 Stage 10-20 問。Mastered 判定後に次 Stage へ進む (完全 gating はしない、7割到達で次 Stage 解放)。

### Stage 1: 金融・統計の基礎スキーマ (10-15 問)

**目的**: 以降すべての用語の prerequisite。

| 用語 | 理由 |
|------|------|
| 株式 (equity, stock) | ETF/指数の基礎 |
| 債券 (bond) | 金利・イールドカーブの基礎 |
| 指数 (index: S&P 500, Nasdaq, SOX) | ETF/VIX の基礎 |
| ETF | 用語 1 (B → A 昇格) |
| リターン (return, %) | 3x レバレッジ・Decay の基礎 |
| ボラティリティ (volatility) | VIX・σ の基礎 |
| 標準偏差 (σ, standard deviation) | 正規分布・sigma 偏差の基礎 |
| 正規分布 (normal distribution) | sigma が「何を意味するか」の基礎 |
| 単純移動平均 (SMA) | SMA20 の基礎 |
| 先物 (futures) | VIX term structure の基礎 |
| オプション (options) | VIX 算出の基礎 |
| 金利 (interest rate) | 債券・NII の基礎 |

### Stage 2: 決算 & マクロ指標 (15-20 問)

**目的**: 私のレポートで毎セッション出てくる概念。

| 用語 | 難易度 |
|------|--------|
| EPS, Revenue, beat/miss | 1 |
| ガイダンス (guidance, forward guidance) | 2 |
| NII (Net Interest Income) | 2 |
| 銀行ビジネスモデル (預金 vs 貸出) | 2 |
| VIX, VIX3M | 2 (Stage 1 options 済が前提) |
| VIX term structure | 3 |
| コンタンゴ / バックワーデーション | 3 |
| イールドカーブ (10Y-2Y spread) | 3 (Stage 1 bond 済が前提) |
| HY spread | 2 |
| ドル指数 (DXY) | 2 |
| Brent / WTI 原油先物 | 2 |
| CPI / PCE / PPI (インフレ指標) | 2 |
| FOMC / Fed funds rate | 2 |
| Section 232 / Section 301 | 2 |

### Stage 3: レバ ETF & トレード実務 (10 問)

**目的**: Stage 1/2 を踏まえた応用層。B 判定の tightening。

| 用語 | 難易度 |
|------|--------|
| 3x レバレッジ ETF (daily reset の厳密理解) | 3 |
| Decay (volatility drag) の数式と実務 | 3 |
| 複利効果の正負両面 | 2 |
| SL / TP / OCO / IFD-OCO | 1 (A 判定済) |
| BE SL の危険性 (K-023 文脈) | 2 |
| Trailing stop | 2 |
| R:R の EV 計算 | 2 |
| gap-up / gap-down | 2 |
| プレマーケット (K-017 文脈) | 2 |

### Stage 4: Master Sensei 独自概念 (10-15 問)

**目的**: プロジェクト固有の語彙・設計。

| 用語 | 難易度 |
|------|--------|
| MAP 分析 (Charter 3.3) | 3 |
| Charter の原則構造 | 2 |
| ADR / GDR (既知、統合で再確認) | 1 |
| knowledge テーブル (K-XXX) | 2 |
| predictions テーブル | 2 |
| events テーブル (impact / relevance) | 2 |
| regime_assessments テーブル (B 判定 tightening) | 2 |
| Brier score | 3 |
| 平均回帰 (K-029 の tightening) | 3 |
| K-017 / K-023 / K-029 / K-034 の中身 | 2 |
| ADR-001 / 003 / 009 の要点 | 2 |

## マスタリー判定

- Box 5 到達 + 2 回連続正解 → **mastered**
- Mastered 達成率が Stage 内 70% 超 → 次 Stage 解放
- 全 Stage mastered 達成時 = 最終 Goal: 私のレポートを未知語ゼロで読める状態

## レビュー頻度

- 未到達 (Box 1-4): Leitner スケジュールに従う (1/2/4/8 日)
- Mastered: 月 1 ランダム再出題 (忘却曲線 anchor)
- Claude の `/learn-status` review: 週 1 目安、mastery 進捗と weak area 分析
