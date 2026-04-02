# Testing Guidelines: 統計・金融コードのテスト設計原則

導入根拠: ADR-020
Created: 2026-04-02

## 目的

統計検定・金融データ処理コードのテストにおける恣意性を排除し、再現性と信頼性を確保する。
一般的なPythonテスト作法（pytest構成等）は対象外。ドメイン固有の指針に絞る。

参考:
- NumPy Testing Guidelines
- Martin Fowler: Eradicating Non-Determinism in Tests
- Phipson & Smyth (2010): Permutation p-values
- The Oracle Problem in Software Testing (IEEE)

## 原則 1: テストの4層構造

統計関数のテストは以下の4層で構成する。1層だけでは不十分。

| 層 | 目的 | 例 |
|----|------|-----|
| **既知解テスト** | 分析的に導出可能な結果の検証 | BH手計算、スプリット 100×0.5=50 |
| **境界テスト** | 判定閾値の前後の動作検証 | 一致率50.1% vs 49.9%、p==threshold |
| **不変量テスト** | 入力に依存しない数学的性質の検証 | p∈[0,1]、BH補正後≦元p値、単調性 |
| **反例テスト** | 失敗すべきケースが失敗することの検証 | ノイズ→不合格、N不足→不合格 |

## 原則 2: seed固定は正当。ただし assert を甘くする理由にしない

- seed を固定して決定論的にするのは正しい（NumPy公式推奨）
- ただし「seed固定で通るから assert は緩くてよい」は誤り
- テスト名が主張する内容を assert で検証すること

**NG例:**
```python
def test_noise_signal_fails(self):  # 名前: "fails"
    result = screen_signal(noise_returns, noise_signal, "long")
    assert result.n_samples > 0  # ← passed を検証していない
```

**OK例:**
```python
def test_noise_signal_structure(self):  # 名前: 構造の検証
    result = screen_signal(noise_returns, noise_signal, "long")
    assert result.n_samples > 0
    assert result.metric_name == "direction_agreement"
```

## 原則 3: 閾値の根拠を明記する

テスト内のマジックナンバーには必ずコメントで根拠を付記する。

**NG例:**
```python
assert result.metric_value > 0.3  # なぜ 0.3？
```

**OK例:**
```python
# 全True信号 + ランダムリターン(mean=0) → 期待一致率50%
# screen_signal閾値>50%なので、偽陽性率の期待値は~50%
# 閾値0.3は期待値50%の下限として十分保守的
assert result.metric_value > 0.3
```

## 原則 4: 境界テストは決定論的データで構築する

境界テストではランダム性を排除し、結果が数学的に確定するデータを使う。

```python
def test_screen_signal_boundary_just_above():
    # 51/100 = 51% → > 50% → passed
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    returns = pd.Series([0.01]*51 + [-0.01]*49, index=dates)
    signal = pd.Series([True]*100, index=dates)
    result = screen_signal(returns, signal, "long")
    assert result.passed is True
    assert result.metric_value == pytest.approx(0.51)
```

## 原則 5: 不変量テストは多様な入力で検証する

数学的に常に成立すべき性質は、複数の入力パターンで検証する。

```python
@pytest.mark.parametrize("seed", [0, 42, 99, 12345])
def test_shuffle_pvalue_in_range(seed):
    # 不変量: p値は常に [0, 1] の範囲内
    ...
    assert 0 <= result.pvalue <= 1
```

## 原則 6: 参照実装との比較

可能な場合、scipy等の参照実装と結果を比較する。

- BH補正 → scipy未実装だが手計算で検証可能
- Spearman相関 → `scipy.stats.spearmanr` と一致確認
- 二項検定 → `scipy.stats.binomtest` と一致確認

## テスト名の命名規則

| パターン | 意味 | assert に含むべきもの |
|---------|------|---------------------|
| `test_X_passes` | X が合格する | `assert result.passed is True` |
| `test_X_fails` | X が不合格になる | `assert result.passed is False` |
| `test_X_structure` | X の出力構造を検証 | フィールド名、型、N>0 等 |
| `test_X_boundary_Y` | 閾値Y付近の動作 | 閾値の上下で結果が変わる |
| `test_X_invariant_Y` | 不変量Yの検証 | 数学的性質（範囲、単調性等） |
| `test_X_reference` | 参照実装との一致 | 既知の正解との比較 |

## 更新ルール

- テスト恣意性のレビューで新たなパターンを発見したら追記する
- 原則の追加にはADR-020への追記は不要（ガイドラインの自律的更新）
