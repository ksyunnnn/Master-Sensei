# 2026Q2 シグナル探索

## 結論

1000仮説空間から314仮説を事前登録し、3,687回の機械実行を経て、**H-18-03（3日連続下落→翌日ロング）が唯一のconfirmedシグナル**。

- TQQQ: 勝率64.8%, 摩擦後+1.42%/回, 年+30.6%
- TECL: 勝率64.2%, 摩擦後+1.50%/回, 年+32.7%
- CSCV 70通り: OOS正リターン率100%

## 詳細

- [方法論と研究品質の評価](2026Q2-methodology-evaluation.md) — Harvey閾値、研究者自由度、Pre-reg遵守度2/5、バイアス監査
- [Stage 1-2 結果](2026Q2-stage1-stage2-results.md) — 3,339実行→48通過→4仮説のフィルタリング過程
- [Stage 3 実用性評価](2026Q2-stage3-evaluation.md) — 摩擦後期待値、コンタンゴ分離、Confirmatory Round

## 判断経緯（Discussion）

### 1. random_data_controlの除外

screen_signalの通過基準（方向一致率>50%）が意図的に緩いため、ランダムリターンでもFP率≈50%となり閾値10%を常に超えた。Stage 1の偽陰性回避思想と矛盾するため除外。実行・記録は維持し、Stage 2でp値ベースで使う方針に変更。

却下した代替案: FP率閾値を60%に緩和（恣意的）、現状維持（bool信号全滅）。

### 2. BH補正のp値ソース変更（shuffle→screen_signal）

shuffle_testの最小p値が1/(n_perms+1)で離散的。m=3,015のBH補正でrank 1閾値0.000066に対し、最小shuffleP=0.000999で原理的に通過不可能。screen_signalのp値（連続）に変更。

バイアス自己チェック: Session 12で「shuffle p値を使う」と推奨した自分の判断ミス。離散性とBH閾値の組み合わせを具体計算していなかった。

### 3. FRED マクロ5年拡張

初期のマクロデータが1年分（update_data.pyのデフォルト: days=365）。統計検出力が不足（n=250 vs 日足n=1254）。FRED APIで9系列5年取得し、マクロ仮説を再実行（通過39→48）。

### 4. 目標10→4→1の過程

当初目標10本。Stage 2で4本に絞られ、摩擦後検証で1本に。バイアス監査（Kahneman 12問）で⚠️9検出、探索打ち切りバイアスを認識。Round 2を追加実施したがR2-TD-01は摩擦後マイナスで不採用。

### 5. VIX百分位レジーム

レジーム安定性テスト用に3案（VIX水準、sensei.duckdb regime、Bull/Bear 200日MA）を比較。VIX百分位を選択した理由: データカバレッジ5年（sensei.duckdbは1年+日飛び）、3分類（Bull/Bearは2分類）、恣意性低（百分位は閾値不要）。

## 次サイクルへの教訓

→ [ADR-013 Lessons Learned](../../../docs/adr/013-entry-signal-research-methodology.md) 参照

## 過程記録

→ [作業ログ](../logs/2026Q2-signal-exploration.log.md)

## データ

```python
import pandas as pd

# 全仮説（344件、status列でfilter）
h = pd.read_parquet("data/research/hypotheses.parquet")
h[h["status"] == "confirmed"]

# 全実行結果（3,687件）
e = pd.read_parquet("data/research/executions.parquet")
e[(e["id"] == "H-18-03") & (e["passed_v2"] == True)]
```
