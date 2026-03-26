"""SenseiDB ユニットテスト"""
from datetime import date, datetime, timezone, timedelta

import pytest

from src.db import SenseiDB, JST


@pytest.fixture
def db(db_conn):
    return SenseiDB(db_conn)


class TestSchema:
    def test_init_creates_all_tables(self, db):
        tables = db.conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        names = {t[0] for t in tables}
        assert names >= {"events", "predictions", "knowledge", "regime_assessments", "event_reviews"}

    def test_init_idempotent(self, db_conn):
        SenseiDB(db_conn)
        SenseiDB(db_conn)


class TestEvents:
    def test_add_event(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        eid = db.add_event(ts, "tariff", "Test event", source_url="https://example.com")
        assert eid == 1

    def test_add_event_dedup(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        eid1 = db.add_event(ts, "tariff", "Test event")
        eid2 = db.add_event(ts, "tariff", "Test event")
        assert eid1 == eid2

    def test_add_event_naive_datetime_raises(self, db):
        with pytest.raises(ValueError, match="timezone-aware"):
            db.add_event(datetime(2026, 3, 26, 10, 0), "tariff", "Bad event")

    def test_get_active_events_excludes_dismissed(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        eid = db.add_event(ts, "tariff", "Dismissed event")
        db.update_event_status(eid, "dismissed")
        db.add_event(datetime(2026, 3, 26, 11, 0, tzinfo=JST), "fed", "Active event")
        active = db.get_active_events()
        assert len(active) == 1
        assert active[0]["category"] == "fed"


class TestPredictions:
    def test_add_prediction(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        pid = db.add_prediction(ts, "VIX > 30 by Friday", date(2026, 3, 28), 0.7, "VIX trending up")
        assert pid == 1

    def test_confidence_validation(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        with pytest.raises(ValueError, match="0.0-1.0"):
            db.add_prediction(ts, "Bad pred", date(2026, 3, 28), 1.5, "Invalid")

    def test_resolve_prediction_calculates_brier(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        pid = db.add_prediction(ts, "VIX > 30", date(2026, 3, 28), 0.8, "VIX up")
        db.resolve_prediction(pid, True, date(2026, 3, 28))
        # Brier = (0.8 - 1.0)^2 = 0.04
        row = db.conn.execute("SELECT brier_score FROM predictions WHERE id = ?", [pid]).fetchone()
        assert abs(row[0] - 0.04) < 1e-9

    def test_resolve_prediction_false_outcome(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        pid = db.add_prediction(ts, "VIX > 30", date(2026, 3, 28), 0.8, "VIX up")
        db.resolve_prediction(pid, False, date(2026, 3, 28))
        # Brier = (0.8 - 0.0)^2 = 0.64
        row = db.conn.execute("SELECT brier_score FROM predictions WHERE id = ?", [pid]).fetchone()
        assert abs(row[0] - 0.64) < 1e-9

    def test_get_pending_predictions(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        db.add_prediction(ts, "Pending", date(2026, 3, 28), 0.6, "test")
        pid2 = db.add_prediction(ts, "Resolved", date(2026, 3, 28), 0.7, "test")
        db.resolve_prediction(pid2, True, date(2026, 3, 28))
        pending = db.get_pending_predictions()
        assert len(pending) == 1
        assert pending[0]["subject"] == "Pending"

    def test_get_brier_score(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        pid1 = db.add_prediction(ts, "P1", date(2026, 3, 28), 0.8, "r1")
        pid2 = db.add_prediction(ts, "P2", date(2026, 3, 28), 0.6, "r2")
        db.resolve_prediction(pid1, True, date(2026, 3, 28))   # 0.04
        db.resolve_prediction(pid2, False, date(2026, 3, 28))  # 0.36
        brier = db.get_brier_score()
        assert abs(brier - 0.20) < 1e-9

    def test_get_calibration_data(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        for i in range(5):
            pid = db.add_prediction(ts, f"P{i}", date(2026, 3, 28), 0.7, "r")
            db.resolve_prediction(pid, i < 4, date(2026, 3, 28))  # 4/5 = 80%
        cal = db.get_calibration_data()
        assert len(cal) == 1
        assert abs(cal[0]["hit_rate"] - 0.8) < 1e-9


class TestKnowledge:
    def test_add_knowledge(self, db):
        kid = db.add_knowledge("K-001", "market_pattern", "VIX > 30 is risk-off", "Historical data")
        assert kid == "K-001"

    def test_add_knowledge_upsert(self, db):
        db.add_knowledge("K-001", "market_pattern", "Original content", "Evidence 1")
        db.add_knowledge("K-001", "market_pattern", "Updated content", "Evidence 2", confidence="high")
        rows = db.conn.execute("SELECT content, confidence FROM knowledge WHERE id = 'K-001'").fetchone()
        assert rows[0] == "Updated content"
        assert rows[1] == "high"

    def test_update_knowledge_status(self, db):
        db.add_knowledge("K-001", "market_pattern", "Test", "Evidence")
        db.update_knowledge_status("K-001", "validated")
        row = db.conn.execute("SELECT verification_status FROM knowledge WHERE id = 'K-001'").fetchone()
        assert row[0] == "validated"

    def test_update_knowledge_invalid_status(self, db):
        db.add_knowledge("K-001", "market_pattern", "Test", "Evidence")
        with pytest.raises(ValueError):
            db.update_knowledge_status("K-001", "bad_status")

    def test_get_active_knowledge_excludes_invalidated(self, db):
        db.add_knowledge("K-001", "market_pattern", "Active", "Evidence")
        db.add_knowledge("K-002", "market_pattern", "Dead", "Evidence")
        db.update_knowledge_status("K-002", "invalidated", reason="Disproven")
        active = db.get_active_knowledge()
        assert len(active) == 1
        assert active[0]["id"] == "K-001"

    def test_get_stale_knowledge(self, db):
        db.add_knowledge("K-001", "market_pattern", "Old", "Evidence", discovered_date=date(2025, 1, 1))
        stale = db.get_stale_knowledge(days=180)
        assert len(stale) == 1


class TestRegime:
    def test_save_and_get_regime(self, db):
        db.save_regime(
            date(2026, 3, 26),
            vix_regime="elevated",
            vix_term_structure="backwardation",
            credit_regime="stressed",
            yield_curve_regime="normal",
            oil_regime="elevated",
            dollar_regime="strong",
            overall="risk_off",
            reasoning="VIX elevated + credit spread widening",
        )
        regime = db.get_latest_regime()
        assert regime["overall"] == "risk_off"
        assert regime["vix_term_structure"] == "backwardation"

    def test_save_regime_upsert(self, db):
        db.save_regime(date(2026, 3, 26), overall="risk_off")
        db.save_regime(date(2026, 3, 26), overall="risk_on")
        regime = db.get_latest_regime()
        assert regime["overall"] == "risk_on"


class TestEventReviews:
    def test_add_review_updates_event_status(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        eid = db.add_event(ts, "tariff", "Test event")
        db.add_event_review(eid, date(2026, 3, 27), "negative", "neutral", "Market ignored it", "Sector-limited impact")
        event = db.conn.execute("SELECT status FROM events WHERE id = ?", [eid]).fetchone()
        assert event[0] == "reviewed"


class TestBiasCheck:
    def test_bias_check_no_data(self, db):
        result = db.get_bias_check()
        assert result["total"] == 0

    def test_bias_check_with_data(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        for i in range(10):
            pid = db.add_prediction(ts, f"P{i}", date(2026, 3, 28), 0.7, "r")
            db.resolve_prediction(pid, i < 7, date(2026, 3, 28))
        result = db.get_bias_check()
        assert result["total"] == 10
        assert result["bullish_pct"] == 100.0  # All confidence > 0.5
