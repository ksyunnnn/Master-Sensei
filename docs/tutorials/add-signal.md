# シグナルの追加手順

新しいシグナルを監視対象に追加するためのチュートリアル。

## 前提

- シグナルがStage 1→2→3を通過し、Confirmatory Roundで confirmed になっていること
- signal_defs.py に信号関数が存在すること

## 手順

### 1. シグナルファイルを作成

`src/signals/` に新しいPythonファイルを作成する。

ファイル名: 仮説IDに対応（例: `h_18_03.py`）

```python
"""H-XX-XX: シグナル名

Status: confirmed (YYYY-MM-DD)
Evidence:
  - 銘柄A XX.X%, 銘柄B XX.X%
  - CSCV結果
  - 摩擦後+X.XX%/回
"""
from src.signal_defs import h_XX_XX  # 既存の信号関数を参照
from src.signals._base import SignalDef

signal = SignalDef(
    id="H-XX-XX",
    name="シグナル名",
    description="判定条件の説明",
    func=h_XX_XX,
    direction="long",  # or "short"
    symbols=["TQQQ", "TECL"],  # 監視対象シンボル
    holding="next_bar",
    status="confirmed",
)
```

必須: モジュールレベルに `signal` という名前の `SignalDef` インスタンスを定義する。

### 2. 動作確認

```bash
python3 -c "
from src.signals import SIGNAL_REGISTRY
for s in SIGNAL_REGISTRY:
    print(f'{s.id}: {s.name} → {s.symbols}')
"
```

新しいシグナルがレジストリに表示されることを確認。

### 3. 発火テスト

```bash
python3 -c "
from src.signals import check_all_signals
from src.research_utils import load_daily
from src.signal_runner import DEFAULT_DAILY_DIR

results = check_all_signals(lambda sym: load_daily(sym, data_dir=DEFAULT_DAILY_DIR))
for r in results:
    mark = 'FIRED' if r.fired else '---'
    print(f'{r.signal_id} {r.symbol}: {mark}')
"
```

### 4. コミット

```bash
git add src/signals/h_XX_XX.py
git commit -m "feat: H-XX-XX をシグナル監視に追加"
```

## チェックリスト

- [ ] Confirmatory Round完了（exploratoryではない）
- [ ] SignalDefの全フィールドを記入
- [ ] docstringにStatus, Evidenceを記載
- [ ] SIGNAL_REGISTRYに自動登録されることを確認
- [ ] /signal-check で正しく判定されることを確認

## 参考

- シグナル基盤の仕様: `src/signals/README.md`
- 信号関数の定義: `src/signal_defs.py`
- 研究の全体像: `data/research/stage1_stage2_report.md`
