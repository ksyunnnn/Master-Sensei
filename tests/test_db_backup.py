"""SenseiDB の git バックアップ export/restore テスト (ADR-033)。

- 蓄積層を CSV で決定的に export する。
- auth_tokens は機密のため絶対に export しない (public repo 漏洩防止)。
- restore は sequence を max(id)+1 に戻し、復元後の採番衝突を防ぐ。
"""

from datetime import datetime, date

import duckdb
import pytest

from src.db import SenseiDB, JST, now_jst, BACKUP_TABLES


def _seed(db: SenseiDB):
    db.add_event(datetime(2026, 3, 28, 15, 0, tzinfo=JST), "tariff", "Event A")
    db.add_event(datetime(2026, 3, 29, 15, 0, tzinfo=JST), "fed", "Event B")
    db.add_prediction(
        now_jst(), "SOXL 上昇", date(2026, 12, 31), 0.6, "理由", category="market"
    )
    db.record_skill_execution("scan-market", now_jst(), "1 event")
    # 機密テーブル: export されないことを検証するために1行入れる
    db.save_token("saxo", "live", "access", "SECRET_TOKEN_VALUE", now_jst())


@pytest.fixture
def db():
    return SenseiDB(duckdb.connect(":memory:"))


def test_export_creates_csv_per_table_and_schema(db, tmp_path):
    _seed(db)
    result = db.export_for_backup(tmp_path)
    for t in BACKUP_TABLES:
        assert (tmp_path / f"{t}.csv").exists(), f"{t}.csv が無い"
    assert (tmp_path / "_schema.sql").exists()
    assert result["tables"]["events"] == 2


def test_export_never_includes_auth_tokens(db, tmp_path):
    """auth_tokens は機密。CSV を出さず、トークン文字列も漏れない (ADR-033)。"""
    _seed(db)
    db.export_for_backup(tmp_path)
    assert not (tmp_path / "auth_tokens.csv").exists()
    assert "auth_tokens" not in BACKUP_TABLES
    blob = "".join(p.read_text() for p in tmp_path.glob("*"))
    assert "SECRET_TOKEN_VALUE" not in blob, "機密トークンが export に漏れている"


def test_export_rejects_auth_tokens_explicitly(db, tmp_path):
    """安全ガード: auth_tokens を明示指定したら例外。"""
    with pytest.raises(ValueError):
        db.export_for_backup(tmp_path, tables=["events", "auth_tokens"])


def test_export_is_deterministic(db, tmp_path):
    """内容不変なら byte 同一 (git 差分ゼロ)。"""
    _seed(db)
    db.export_for_backup(tmp_path)
    first = (tmp_path / "events.csv").read_bytes()
    db.export_for_backup(tmp_path)
    second = (tmp_path / "events.csv").read_bytes()
    assert first == second


def test_restore_round_trips_counts(db, tmp_path):
    _seed(db)
    db.export_for_backup(tmp_path)

    fresh = SenseiDB(duckdb.connect(":memory:"))
    fresh.restore_from_backup(tmp_path)
    assert len(fresh.get_active_events()) == 2
    assert fresh.conn.execute("SELECT count(*) FROM predictions").fetchone()[0] == 1


def test_restore_resets_sequences_to_avoid_id_collision(db, tmp_path):
    """復元後に新規 add_event した id が衝突しない (max+1 から採番)。"""
    _seed(db)  # events id 1,2
    db.export_for_backup(tmp_path)

    fresh = SenseiDB(duckdb.connect(":memory:"))
    fresh.restore_from_backup(tmp_path)
    new_id = fresh.add_event(datetime(2026, 4, 1, 15, 0, tzinfo=JST), "market", "Event C")
    assert new_id == 3, f"sequence 未復元: 期待 id=3, 実際 {new_id}"
