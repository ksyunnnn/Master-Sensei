# ADR-021: シグナル定義と探索の実装方式

Status: accepted
Date: 2026-04-02

## Concept

**Dig with intent, verify with discipline.**

1000のアイデアから10の宝を見つける。全てを等しく篩うのではなく、
有望な場所を深く掘り、見つけたものを厳密に検証する。
発見の喜びと統計的誠実さを両立する。

## Context

ADR-013で設計した3段階ファネル（1000→100→10）の実行にあたり、
193サブシグナル（68カテゴリ）を実行可能なコードに変換する必要がある。

### 本質的な問い

「砂を落とす（機械的フィルタ）」と「宝を探す（能動的発見）」は
相反するように見えるが、創薬では両立している:

- **Hit finding**（探索）: 広くスクリーニング + 有望領域を深掘り
- **Hit confirmation**（確認）: 事前登録した基準で厳密に検証

探索と確認を**同一フェーズで混ぜない**ことが鍵。

### 調査した手法

| 手法 | 採用判断 | 理由 |
|------|---------|------|
| AlphaAgent (3-Agent分業) | 探索フェーズに採用 | Idea→Factor→Eval の分離。結果からの新仮説生成 |
| Pre-Analysis Plan (PAP) | 確認フェーズに採用 | 定義コミット=ロック。p-hacking防止の最も信頼性の高い手法 |
| DFS (composable primitives) | 不採用 | フレームワークのオーバーヘッド。Charter 3.5違反 |
| tsfresh (全特徴量 + 統計フィルタ) | 不採用 | 仮説駆動アプローチを放棄することになる |

## Decision

> 2ラウンド制: 確認ラウンド（機械的検証）→ 探索ラウンド（発見と深掘り）。
> 探索で生まれた新仮説は次の確認ラウンドに回す。

### Round 1: 確認（Confirmatory）

既知の193仮説を事前登録し、機械的に検証する。

```
src/signal_defs.py    — ヘルパー関数(~30) + 信号生成関数 + HYPOTHESES リスト
src/signal_runner.py  — HYPOTHESES を読み、screen_signal + 反証テストを機械実行
```

- signal_defs.py をコミットした時点で Pre-Analysis Plan ロック
- signal_runner.py はAgent裁量なし。判断ロジックゼロ
- 全試行を signal_ideas.csv に記録（ADR-013準拠）
- 計算量: 372仮説 × 18シンボル ≈ 3分。並列化不要

### Round 2: 探索（Exploratory）

Round 1の結果を分析し、新しい仮説を生む。

- **なぜ通った？** — 通過シグナルの共通パターン、レジーム依存性、シンボル間差異
- **なぜ落ちた？** — 僅差で落ちた仮説の改良可能性、パラメータ感度
- **組み合わせ** — 独立に通過したシグナル同士のアンサンブル効果
- **想定外の発見** — データが示す予想外のパターン

探索結果は明示的に「exploratory」とラベルし、次回の確認ラウンドの
signal_defs.py に追加してから再検証する。

### signal_defs.py の構造

```python
# ── ヘルパー関数（共通計算ロジック）──
def _rsi(close: pd.Series, period: int = 14) -> pd.Series: ...
def _ma_deviation(close: pd.Series, period: int) -> pd.Series: ...
def _gap(open_: pd.Series, prev_close: pd.Series) -> pd.Series: ...
# ... ~30個

# ── 信号生成関数（1仮説 = 1関数）──
def h_01_01(df): return _gap(df['Open'], df['Close'].shift(1)) > 0
def h_01_05a(df): return _rsi(df['Close'], 14) < 30
# ...

# ── 仮説リスト（Pre-Analysis Plan）──
HYPOTHESES = [
    {"id": "H-01-01", "func": h_01_01, "direction": "long",
     "timeframe": "daily", "bias_test_type": "unconditional"},
    # ... 全仮説を事前列挙
]
```

### レビュー戦略

| 対象 | 方法 |
|------|------|
| ヘルパー関数(~30個) | 全件レビュー + テスト |
| 信号生成関数(~370個) | 構造レビュー + bias_test_type ごとに代表件を詳細確認 |
| HYPOTHESES リスト | hypothesis_space.md との対応を自動チェック（漏れ・重複検出） |

### 作成手順

1. ヘルパー関数を TDD で実装
2. LLM が hypothesis_space.md から信号生成関数 + HYPOTHESES の初期ドラフトを生成
3. 自動チェック: 呼び出し可能性、戻り値型、カバレッジ
4. 人間が構造 + 代表件をレビュー
5. コミット = ロック
6. signal_runner.py で Round 1 実行
7. 結果を分析し Round 2（探索）を実施

## Rationale

- **Charter 3.5**: 関数 + リストは最小限の抽象。フレームワークなし
- **ADR-013 対策3**: Round 1のシグナル生成は事前定義。Agent裁量なし
- **PAP研究知見**: Pre-Analysis Planを伴うpre-registrationのみがp-hackingを有意に低下させる
- **宝探しとの両立**: Round 2で発見・深掘りの余地を確保。ただし確認は常にRound 1方式

## Consequences

- ADR-013の「4並列Agent」をRound 1では「単一スクリプト」に縮小。Round 2では分析にAgentを活用
- signal_defs.py がPre-Analysis Plan。コミット後の変更は新仮説として追記（既存定義は不変）
- タスク d-pre（Parquetスキーマ拡充）は不要。signal_defs.py が仮説定義のSoT
- 探索ラウンドの結果は exploratory ラベル付きで記録。確認前に実弾判断に使わない
- 見直しトリガー: Round 1完了後、通過率が5%未満 or 50%超の場合はフィルタ基準を再評価
