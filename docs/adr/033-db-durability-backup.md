# ADR-033: sensei.duckdb の耐久性・gitバックアップ方針

Status: accepted
Date: 2026-06-17

## Context

`data/sensei.duckdb` は判断・知見の蓄積層（events / predictions / knowledge / regime_assessments
/ event_reviews / trades / skill_executions）を保持する。これらは手で積み上げた分析であり、
**外部から再生できない**（価格 parquet は Tiingo/FRED から再取得でき、Saxo 執行事実層は
再 import できるが、知見・予測・トレード台帳は失えば終わり）。

調査の結果、消失対策が実質ゼロだった:
- `.gitignore` で `data/*.duckdb` 除外 → バージョン管理外。GitHub にも無い。
- backup スクリプト・cron・hook いずれも無し。
- 唯一のコピーはローカル単一ファイル。マシン故障で蓄積知見が消える。

## Decision

蓄積層を **CSV で git 追跡ディレクトリ `data/db_export/` に EXPORT し、GitHub にコミット**する
ことでオフサイト・バージョン管理されたバックアップとする。

### 形式と除外

- 形式: **CSV**（テキスト＝差分が見える・内容不変なら byte 同一でコミット不要）。
  各テーブル `data/db_export/<table>.csv` ＋ スキーマ DDL `data/db_export/_schema.sql`。
- 決定性: `COPY (SELECT * FROM t ORDER BY ALL) TO ...` で行順を固定。**変更が無ければ git 差分ゼロ**。
- **`auth_tokens` は除外（必須）**。OAuth access/refresh トークンを含み、**public repo への
  コミットは認証情報漏洩**。かつ OAuth で再生可能・常時変動で git ノイズ源。
  `export_for_backup` は `auth_tokens` 指定時に例外を投げる安全ガードを持つ。

### 実行タイミング（Stop フックは肥大化させない）

- **`python update_data.py` の末尾で自動実行**（`--no-backup` で抑止可）。データ更新の
  ついでにバックアップが回る。内容不変なら git 差分が出ないので頻繁実行も無害。
- **任意タイミングは `python scripts/backup_db.py`**（単独 CLI）。
- **Stop フックには追加しない**（既に肥大のため、ユーザー方針）。

### 復元

`scripts/backup_db.py --restore` または `SenseiDB.restore_from_backup(dir)`:
1. 空の SenseiDB を生成（`_init_schema` でテーブル＋sequence 作成）。
2. 各 CSV を `COPY <table> FROM ...` で投入。
3. **sequence を `max(id)+1` に再設定**（events/predictions/skill_executions/trades）。
   CSV はsequence 状態を持たないため、これを怠ると復元後の採番が id 1 から衝突する。
   knowledge.id は文字列 "K-044"、regime_assessments/event_reviews は id 無しで対象外。

## Consequences

- 蓄積知見が GitHub 上に常時退避され、マシン故障・ファイル破損に耐える。
- auth_tokens は意図的に退避しない（漏洩防止）。復元後は OAuth 再取得が必要。
- バックアップは「中身が変わった時だけ」git 差分を生む＝コミット履歴が意味を持つ。
- 価格 parquet・5分足は引き続き git 管理外（再取得可能、ただし 5分足の 128 営業日超は
  非可逆＝この方針の対象外。必要なら別途検討）。

## 関連

- ADR-001（データアーキテクチャ: 何を DuckDB に置くか）
- ADR-025（auth_tokens＝機密の所在）、ADR-003（Write 基準）
