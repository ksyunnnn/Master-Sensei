"""SenseiDB ユニットテスト"""
from datetime import date, datetime, timezone, timedelta

import pytest

from src.db import SenseiDB, JST, now_jst, today_jst


@pytest.fixture
def db(db_conn):
    return SenseiDB(db_conn)


class TestTimeHelpers:
    def test_now_jst_returns_aware_datetime_with_jst(self):
        result = now_jst()
        assert isinstance(result, datetime)
        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(hours=9)

    def test_today_jst_returns_date(self):
        result = today_jst()
        assert isinstance(result, date)
        assert not isinstance(result, datetime)


class TestSchema:
    def test_init_creates_all_tables(self, db):
        tables = db.conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        names = {t[0] for t in tables}
        assert names >= {"events", "predictions", "knowledge", "regime_assessments", "event_reviews", "skill_executions"}
        assert "market_observations" not in names  # ADR-009: 廃止

    def test_regime_assessments_has_snapshot_columns(self, db):
        """ADR-009: regime_assessmentsに入力値スナップショットカラムが存在する"""
        cols = db.conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'regime_assessments' AND table_schema = 'main'"
        ).fetchall()
        col_names = {c[0] for c in cols}
        snapshot_cols = {"vix_value", "vix3m_value", "hy_spread_value", "yield_curve_value", "oil_value", "usd_value"}
        assert snapshot_cols <= col_names

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

    def test_save_regime_with_snapshot(self, db):
        """ADR-009: 入力値スナップショットが保存・取得できる"""
        db.save_regime(
            date(2026, 3, 28),
            vix_regime="high",
            vix_term_structure="backwardation",
            credit_regime="normal",
            yield_curve_regime="normal",
            oil_regime="elevated",
            dollar_regime="normal",
            overall="risk_off",
            reasoning="VIX 26.9 > 25",
            vix_value=26.9,
            vix3m_value=26.5,
            hy_spread_value=3.19,
            yield_curve_value=0.49,
            oil_value=103.8,
            usd_value=104.2,
        )
        regime = db.get_latest_regime()
        assert regime["vix_value"] == 26.9
        assert regime["vix3m_value"] == 26.5
        assert regime["hy_spread_value"] == 3.19
        assert regime["yield_curve_value"] == 0.49
        assert regime["oil_value"] == 103.8
        assert regime["usd_value"] == 104.2

    def test_save_regime_snapshot_nullable(self, db):
        """ADR-009: スナップショットカラムはNULL許容（API障害時）"""
        import math
        db.save_regime(
            date(2026, 3, 28),
            overall="risk_off",
            reasoning="Partial data",
            vix_value=26.9,
        )
        regime = db.get_latest_regime()
        assert regime["vix_value"] == 26.9
        # DuckDB returns NaN for NULL DOUBLE via fetchdf().to_dict()
        assert regime["vix3m_value"] is None or math.isnan(regime["vix3m_value"])


class TestEvents:
    def test_add_event_with_source(self, db):
        """events.source列で登録経路を記録"""
        ts = datetime(2026, 3, 28, 10, 0, tzinfo=JST)
        eid = db.add_event(ts, "geopolitical", "Test event", source="scan-market")
        row = db.conn.execute("SELECT source FROM events WHERE id = ?", [eid]).fetchone()
        assert row[0] == "scan-market"

    def test_add_event_source_defaults_to_manual(self, db):
        """source未指定時はmanual"""
        ts = datetime(2026, 3, 28, 10, 0, tzinfo=JST)
        eid = db.add_event(ts, "fed", "Test event")
        row = db.conn.execute("SELECT source FROM events WHERE id = ?", [eid]).fetchone()
        assert row[0] == "manual"


class TestSkillExecutions:
    def test_record_skill_execution(self, db):
        ts = datetime(2026, 3, 28, 23, 55, tzinfo=JST)
        exec_id = db.record_skill_execution(
            skill_name="scan-market",
            executed_at=ts,
            result_summary="6 events added",
            metadata='{"latest_source_date": "2026-03-28T15:00:00+09:00"}',
        )
        assert exec_id >= 1

    def test_get_last_skill_execution(self, db):
        ts1 = datetime(2026, 3, 27, 10, 0, tzinfo=JST)
        ts2 = datetime(2026, 3, 28, 10, 0, tzinfo=JST)
        db.record_skill_execution("scan-market", ts1, "3 events added")
        db.record_skill_execution("scan-market", ts2, "6 events added")
        db.record_skill_execution("update-regime", ts2, "regime updated")

        last = db.get_last_skill_execution("scan-market")
        assert last is not None
        assert last["result_summary"] == "6 events added"

    def test_get_last_skill_execution_none(self, db):
        last = db.get_last_skill_execution("scan-market")
        assert last is None

    def test_record_skill_execution_naive_datetime_raises(self, db):
        with pytest.raises(ValueError, match="timezone-aware"):
            db.record_skill_execution("scan-market", datetime(2026, 3, 28, 10, 0), "test")


class TestEventReviews:
    def test_add_review_updates_event_status(self, db):
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        eid = db.add_event(ts, "tariff", "Test event")
        db.add_event_review(eid, date(2026, 3, 27), "negative", "neutral", "Market ignored it", "Sector-limited impact")
        event = db.conn.execute("SELECT status FROM events WHERE id = ?", [eid]).fetchone()
        assert event[0] == "reviewed"


class TestGDR001Phase1:
    """GDR-001 Phase 1: source_prediction_id, root_cause_category, Brier 3成分分解"""

    def test_knowledge_has_source_prediction_id(self, db):
        """knowledgeテーブルにsource_prediction_idカラムが存在する"""
        cols = db.conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'knowledge' AND table_schema = 'main'"
        ).fetchall()
        assert "source_prediction_id" in {c[0] for c in cols}

    def test_predictions_has_root_cause_category(self, db):
        """predictionsテーブルにroot_cause_categoryカラムが存在する"""
        cols = db.conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'predictions' AND table_schema = 'main'"
        ).fetchall()
        assert "root_cause_category" in {c[0] for c in cols}

    def test_add_knowledge_with_source_prediction(self, db):
        """source_prediction_idを指定して知見を追加できる"""
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        pid = db.add_prediction(ts, "VIX<25", date(2026, 3, 28), 0.45, "test")
        db.resolve_prediction(pid, False, date(2026, 3, 28))

        kid = db.add_knowledge("K-TEST", "meta", "lesson", "evidence",
                               source_prediction_id=pid)
        row = db.conn.execute(
            "SELECT source_prediction_id FROM knowledge WHERE id = ?", [kid]
        ).fetchone()
        assert row[0] == pid

    def test_resolve_with_root_cause(self, db):
        """予測解決時にroot_cause_categoryを記録できる"""
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        pid = db.add_prediction(ts, "VIX<25", date(2026, 3, 28), 0.45, "test")
        db.resolve_prediction(pid, False, date(2026, 3, 28),
                              root_cause_category="overconfidence")
        row = db.conn.execute(
            "SELECT root_cause_category FROM predictions WHERE id = ?", [pid]
        ).fetchone()
        assert row[0] == "overconfidence"

    def test_brier_decomposition_single(self, db):
        """Brier 3成分分解: 1件でも算出可能（退化ケース）"""
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        pid = db.add_prediction(ts, "P1", date(2026, 3, 28), 0.7, "r")
        db.resolve_prediction(pid, True, date(2026, 3, 28))
        result = db.get_brier_decomposition()
        assert "reliability" in result
        assert "resolution" in result
        assert "uncertainty" in result
        assert "brier_score" in result

    def test_brier_decomposition_multiple(self, db):
        """Brier 3成分分解: Brier = Reliability - Resolution + Uncertainty"""
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        data = [(0.9, True), (0.8, True), (0.7, True), (0.6, False),
                (0.4, True), (0.3, False), (0.2, False), (0.1, False)]
        for conf, outcome in data:
            pid = db.add_prediction(ts, f"P-{conf}", date(2026, 3, 28), conf, "r")
            db.resolve_prediction(pid, outcome, date(2026, 3, 28))

        result = db.get_brier_decomposition()
        # Brier = Reliability - Resolution + Uncertainty (Murphy 1973)
        expected_brier = result["reliability"] - result["resolution"] + result["uncertainty"]
        assert abs(result["brier_score"] - expected_brier) < 1e-10

    def test_baseline_score(self, db):
        """Baseline Score: 50%ベースラインとの比較"""
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        # 完璧な予測: Brier=0 < Baseline=0.25
        pid = db.add_prediction(ts, "P1", date(2026, 3, 28), 1.0, "r")
        db.resolve_prediction(pid, True, date(2026, 3, 28))
        result = db.get_baseline_score()
        assert result["baseline_brier"] == 0.25
        assert result["skill_score"] > 0  # 50%より良い

    def test_kolb_cycle_rate(self, db):
        """Kolbサイクル完遂率: 予測→解決→知見の連鎖"""
        ts = datetime(2026, 3, 26, 10, 0, tzinfo=JST)
        pid1 = db.add_prediction(ts, "P1", date(2026, 3, 28), 0.7, "r")
        pid2 = db.add_prediction(ts, "P2", date(2026, 3, 28), 0.6, "r")
        db.resolve_prediction(pid1, True, date(2026, 3, 28))
        db.resolve_prediction(pid2, False, date(2026, 3, 28))
        # pid1にだけ知見を紐付け
        db.add_knowledge("K-T1", "meta", "lesson", "ev", source_prediction_id=pid1)

        rate = db.get_kolb_cycle_rate()
        assert rate["resolved"] == 2
        assert rate["with_knowledge"] == 1
        assert rate["completion_rate"] == 0.5


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


class TestTrades:
    """ADR-015: トレード記録"""

    def test_schema_has_trades_table(self, db):
        tables = db.conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        assert "trades" in {t[0] for t in tables}

    def test_trades_has_all_columns(self, db):
        cols = db.conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'trades' AND table_schema = 'main'"
        ).fetchall()
        col_names = {c[0] for c in cols}
        expected = {
            "id", "instrument", "direction", "entry_date", "entry_price",
            "exit_date", "exit_price", "quantity", "pnl_usd", "pnl_pct",
            "commission_usd", "holding_days",
            "regime_at_entry", "vix_at_entry", "brent_at_entry",
            "confidence_at_entry", "setup_type", "entry_reasoning", "exit_reasoning",
            "discipline_score", "review_notes", "prediction_id", "created_at",
        }
        assert expected <= col_names

    def test_add_trade(self, db):
        tid = db.add_trade(
            instrument="SOXL",
            direction="long",
            entry_date=date(2026, 3, 31),
            entry_price=42.949,
            quantity=28,
            regime_at_entry="risk_off",
            vix_at_entry=28.92,
            brent_at_entry=107.94,
            confidence_at_entry=0.65,
            setup_type="de_escalation_bounce",
            entry_reasoning="WSJ peace signal + TurboQuant reversal",
        )
        assert tid == 1

    def test_add_trade_returns_incremental_id(self, db):
        tid1 = db.add_trade(
            instrument="SOXL", direction="long",
            entry_date=date(2026, 3, 31), entry_price=42.949, quantity=28,
        )
        tid2 = db.add_trade(
            instrument="TQQQ", direction="long",
            entry_date=date(2026, 3, 31), entry_price=39.0, quantity=30,
        )
        assert tid2 == tid1 + 1

    def test_close_trade(self, db):
        tid = db.add_trade(
            instrument="SOXL", direction="long",
            entry_date=date(2026, 3, 31), entry_price=42.949, quantity=28,
        )
        db.close_trade(
            trade_id=tid,
            exit_date=date(2026, 3, 31),
            exit_price=47.24,
            exit_reasoning="OCO take profit hit",
        )
        row = db.conn.execute("SELECT * FROM trades WHERE id = ?", [tid]).fetchdf().to_dict("records")[0]
        assert row["exit_price"] == 47.24
        assert abs(row["pnl_usd"] - (47.24 - 42.949) * 28) < 0.01
        assert abs(row["pnl_pct"] - ((47.24 / 42.949) - 1) * 100) < 0.01
        assert row["holding_days"] == 0  # same day

    def test_close_trade_multiday(self, db):
        tid = db.add_trade(
            instrument="SOXL", direction="long",
            entry_date=date(2026, 3, 28), entry_price=46.61, quantity=10,
        )
        db.close_trade(tid, exit_date=date(2026, 3, 31), exit_price=47.91)
        row = db.conn.execute("SELECT holding_days FROM trades WHERE id = ?", [tid]).fetchone()
        assert row[0] == 3

    def test_close_trade_short_direction(self, db):
        tid = db.add_trade(
            instrument="SOXS", direction="short",
            entry_date=date(2026, 3, 31), entry_price=48.74, quantity=10,
        )
        db.close_trade(tid, exit_date=date(2026, 3, 31), exit_price=39.86)
        row = db.conn.execute("SELECT pnl_usd, pnl_pct FROM trades WHERE id = ?", [tid]).fetchone()
        # Short: profit when price goes down
        assert row[0] > 0  # positive PnL
        assert row[1] > 0  # positive pct

    def test_review_trade(self, db):
        tid = db.add_trade(
            instrument="SOXL", direction="long",
            entry_date=date(2026, 3, 31), entry_price=42.949, quantity=28,
        )
        db.close_trade(tid, exit_date=date(2026, 3, 31), exit_price=47.24)
        db.review_trade(tid, discipline_score=4, review_notes="Followed the plan. OCO worked well.")
        row = db.conn.execute(
            "SELECT discipline_score, review_notes FROM trades WHERE id = ?", [tid]
        ).fetchone()
        assert row[0] == 4
        assert "OCO" in row[1]

    def test_review_trade_discipline_validation(self, db):
        tid = db.add_trade(
            instrument="SOXL", direction="long",
            entry_date=date(2026, 3, 31), entry_price=42.949, quantity=28,
        )
        with pytest.raises(ValueError, match="1-5"):
            db.review_trade(tid, discipline_score=6)

    def test_get_open_trades(self, db):
        db.add_trade(
            instrument="SOXL", direction="long",
            entry_date=date(2026, 3, 31), entry_price=42.949, quantity=28,
        )
        tid2 = db.add_trade(
            instrument="TQQQ", direction="long",
            entry_date=date(2026, 3, 31), entry_price=39.0, quantity=30,
        )
        db.close_trade(tid2, exit_date=date(2026, 3, 31), exit_price=41.0)
        open_trades = db.get_open_trades()
        assert len(open_trades) == 1
        assert open_trades[0]["instrument"] == "SOXL"
