# Learning Drill

Master Sensei の金融・投資用語を公文式スタイルで定着させるための独立ドリルアプリ。

## Usage

```bash
python drill.py                 # 今日のドリル (5 問、due + 新問の混合)
python drill.py -n 10           # 10 問セッション
python drill.py --stats         # 進捗サマリのみ表示
python drill.py --reload        # 質問 Markdown を手動再ロード (起動時は自動)
python drill.py --stage 2       # due 切れ時、Stage 2 から新問を出す
```

## Structure

```
learning/
├── __init__.py
├── db.py           # DuckDB schema + CRUD (Question / Mastery)
├── scheduler.py    # Leitner 5-box scheduler (pure function)
├── loader.py       # Markdown → Question parser
├── cli.py          # Interactive CLI
├── timeutil.py     # JST timezone utilities (self-contained)
├── data/
│   ├── drill.duckdb        # 自動生成、gitignored
│   └── questions/          # 質問マスター (Markdown + front matter)
├── docs/
│   ├── curriculum.md       # Stage 1-4 設計 + 診断結果
│   ├── adr/                # 個別アーキ判断
│   └── history/            # 時系列ジャーニー
├── tests/
│   └── test_learning.py    # scheduler / db / loader の単体テスト
├── CHANGELOG.md
└── README.md               # このファイル
```

Entry point (`drill.py`) は repo root に置く。本アプリの他のファイルは `learning/` 配下に閉じている。

## Design rationale

- 個別判断は `docs/adr/` を参照 (MADR 形式)
- 全体の経緯・設計ジャーニーは `docs/history/` を参照
- 版管理は `CHANGELOG.md`

## Dependencies

- Python 3.12+
- `duckdb` (Python package)

`requirements.txt` は親プロジェクトのものを共用している (sensei.duckdb 本体と重複が少ないため意図的)。将来的に完全分離する場合は `learning/requirements.txt` に切り出す。
