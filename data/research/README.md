# エントリーシグナル研究

## 現在地

- **Cycle 1完了**: H-18-03（3日連続下落→ロング）がconfirmed
- **実弾化**: src/signals/h_18_03.py + /signal-checkスキル 実装済み
- **次のCycle**: 未定（マージ→実運用が先）

## ここから読む

1. [findings/2026Q2-signal-exploration.md](findings/2026Q2-signal-exploration.md) — Cycle 1の成果（MOC、ここから詳細へ遷移）
2. [references/research-storage-design.md](references/research-storage-design.md) — このディレクトリの設計根拠

## データのクエリ

```python
import pandas as pd

# 全仮説（344件）
h = pd.read_parquet("data/research/hypotheses.parquet")

# confirmedのみ
h[h["status"] == "confirmed"]

# 全実行結果（3,687件）
e = pd.read_parquet("data/research/executions.parquet")

# 特定仮説の全シンボル結果
e[e["id"] == "H-18-03"]

# Stage 1通過分
e[e["passed_v2"] == True]

# DuckDBからクエリ（Parquetを直接読み込み）
# SELECT * FROM read_parquet('data/research/executions.parquet') WHERE id = 'H-18-03'
```

## ディレクトリ構成

```
data/research/
  README.md              ← この文書（入口）
  hypotheses.parquet     ← 全仮説（累積）
  executions.parquet     ← 全実行結果（累積）
  findings/              ← サイクル成果（凍結）
  logs/                  ← 作業過程記録（凍結）
  references/            ← 不変参照資料
```

## 未決の検討事項

1. 探索をやり直すか（目標10本に対して1本）
2. シグナル監視アーキテクチャ（ECA + レイヤード/Hexagonal、../app/との統合）
3. H-18-03の2日/4日連続を独立シグナルとして追加採用するか
