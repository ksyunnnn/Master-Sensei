# signals/ — シグナル監視基盤

## 概要

確認済み（confirmed）シグナルの定義と自動レジストリ。ECAアーキテクチャのCondition層。

## 構成

```
signals/
  __init__.py    — 自動レジストリ（配下のモジュールを走査してSIGNAL_REGISTRYに登録）
  _base.py       — SignalDef, SignalResult, check_signal()
  h_18_03.py     — H-18-03: 3日連続下落→ロング
  README.md      — このファイル
```

## SignalDef 仕様

| フィールド | 型 | 説明 |
|-----------|-----|------|
| id | str | 仮説ID（例: "H-18-03"） |
| name | str | 日本語名（例: "連続3日下落→ロング"） |
| description | str | 判定条件の説明 |
| func | Callable[[DataFrame], Series] | signal_defs.pyの関数を参照 |
| direction | str | "long" or "short" |
| symbols | list[str] | 監視対象シンボル |
| holding | str | 保有期間（デフォルト: "next_bar"） |
| status | str | "confirmed" or "exploratory" |

## ファイル命名規則

- `h_XX_XX.py` — Round 1由来の仮説（signal_defs.pyのh_XX_XX関数に対応）
- `r2_XX_XX.py` — Round 2由来の探索的仮説
- `_` で始まるファイル — レジストリ対象外（_base.py等）

## 自動レジストリの仕組み

`__init__.py` がimport時に配下の全モジュールを走査し、`signal` 属性（SignalDef型）を持つモジュールを `SIGNAL_REGISTRY` に登録する。

```python
from src.signals import SIGNAL_REGISTRY
# → [SignalDef(id="H-18-03", ...)]
```

## 判定の仕組み

`check_signal(signal_def, load_fn)` が:
1. 各シンボルでload_fnを呼びDataFrameを取得
2. signal_def.funcを実行しSeriesを取得
3. 最終行の値で発火/非発火を判定
4. SignalResultのリストを返す
