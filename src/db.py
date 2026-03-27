"""Master Sensei DuckDBスキーマ定義・CRUD操作

テーブル:
- events: マクロイベント記録
- predictions: 予測記録（Brier score計測用）
- knowledge: 知見DB（パターン・ルール蓄積）
- regime_assessments: レジーム判定
- event_reviews: イベント事後検証
- market_observations: 手動マクロデータ投入（ADR-005）
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import duckdb

JST = timezone(offset=__import__("datetime").timedelta(hours=9))


def _require_aware(dt: datetime, param_name: str = "dt") -> datetime:
    if dt.tzinfo is None:
        raise ValueError(
            f"{param_name} must be timezone-aware. Got naive datetime."
        )
    return dt


class SenseiDB:
    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self.conn = conn
        self.conn.execute("SET TIMEZONE = 'Asia/Tokyo'")
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                event_timestamp TIMESTAMPTZ NOT NULL,
                category VARCHAR NOT NULL,
                summary VARCHAR NOT NULL,
                impact VARCHAR,
                impact_reasoning VARCHAR,
                relevance VARCHAR,
                source_url VARCHAR,
                status VARCHAR DEFAULT 'unreviewed',
                created_at TIMESTAMP DEFAULT current_timestamp
            )
        """)
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS events_id_seq START 1")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL,
                subject VARCHAR NOT NULL,
                deadline DATE NOT NULL,
                confidence DOUBLE NOT NULL,
                reasoning VARCHAR NOT NULL,
                falsification VARCHAR,
                outcome BOOLEAN,
                outcome_date DATE,
                outcome_notes VARCHAR,
                brier_score DOUBLE,
                category VARCHAR DEFAULT 'market'
            )
        """)
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS predictions_id_seq START 1")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id VARCHAR PRIMARY KEY,
                category VARCHAR NOT NULL,
                content VARCHAR NOT NULL,
                evidence VARCHAR NOT NULL,
                confidence VARCHAR NOT NULL DEFAULT 'low',
                verification_status VARCHAR NOT NULL DEFAULT 'hypothesis',
                discovered_date DATE NOT NULL,
                last_verified_date DATE,
                invalidation_reason VARCHAR,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS regime_assessments (
                date DATE PRIMARY KEY,
                vix_regime VARCHAR,
                vix_term_structure VARCHAR,
                credit_regime VARCHAR,
                yield_curve_regime VARCHAR,
                oil_regime VARCHAR,
                dollar_regime VARCHAR,
                overall VARCHAR,
                reasoning VARCHAR,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS market_observations (
                date DATE NOT NULL,
                series VARCHAR NOT NULL,
                value DOUBLE NOT NULL,
                source VARCHAR NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL,
                status VARCHAR DEFAULT 'unverified',
                PRIMARY KEY (date, series, source)
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS event_reviews (
                event_id INTEGER NOT NULL,
                review_date DATE NOT NULL,
                original_impact VARCHAR,
                revised_impact VARCHAR,
                actual_outcome VARCHAR,
                lesson VARCHAR,
                created_at TIMESTAMP DEFAULT current_timestamp,
                PRIMARY KEY (event_id, review_date)
            )
        """)

    # ── events ──

    def add_event(
        self,
        event_timestamp: datetime,
        category: str,
        summary: str,
        *,
        impact: str = None,
        impact_reasoning: str = None,
        relevance: str = None,
        source_url: str = None,
    ) -> int:
        _require_aware(event_timestamp, "event_timestamp")
        existing = self.conn.execute(
            "SELECT id FROM events WHERE event_timestamp = ? AND category = ? AND summary = ?",
            [event_timestamp, category, summary],
        ).fetchone()
        if existing:
            return existing[0]

        event_id = self.conn.execute("SELECT nextval('events_id_seq')").fetchone()[0]
        self.conn.execute("""
            INSERT INTO events (id, event_timestamp, category, summary, impact, impact_reasoning, relevance, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [event_id, event_timestamp, category, summary, impact, impact_reasoning, relevance, source_url])
        return event_id

    def get_active_events(self) -> list[dict]:
        return self.conn.execute(
            "SELECT * FROM events WHERE status != 'dismissed' ORDER BY event_timestamp DESC"
        ).fetchdf().to_dict("records")

    def update_event_status(self, event_id: int, status: str):
        self.conn.execute("UPDATE events SET status = ? WHERE id = ?", [status, event_id])

    # ── predictions ──

    def add_prediction(
        self,
        created_at: datetime,
        subject: str,
        deadline: date,
        confidence: float,
        reasoning: str,
        *,
        falsification: str = None,
        category: str = "market",
    ) -> int:
        _require_aware(created_at, "created_at")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"confidence must be 0.0-1.0, got {confidence}")

        pred_id = self.conn.execute("SELECT nextval('predictions_id_seq')").fetchone()[0]
        self.conn.execute("""
            INSERT INTO predictions (id, created_at, subject, deadline, confidence, reasoning, falsification, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [pred_id, created_at, subject, deadline, confidence, reasoning, falsification, category])
        return pred_id

    def resolve_prediction(
        self,
        pred_id: int,
        outcome: bool,
        outcome_date: date,
        outcome_notes: str = None,
    ):
        row = self.conn.execute("SELECT confidence FROM predictions WHERE id = ?", [pred_id]).fetchone()
        if not row:
            raise ValueError(f"Prediction {pred_id} not found")
        confidence = row[0]
        brier = (confidence - (1.0 if outcome else 0.0)) ** 2

        self.conn.execute("""
            UPDATE predictions
            SET outcome = ?, outcome_date = ?, outcome_notes = ?, brier_score = ?
            WHERE id = ?
        """, [outcome, outcome_date, outcome_notes, brier, pred_id])

    def get_pending_predictions(self) -> list[dict]:
        return self.conn.execute(
            "SELECT * FROM predictions WHERE outcome IS NULL ORDER BY deadline"
        ).fetchdf().to_dict("records")

    def get_prediction_counts(self) -> dict:
        """予測の件数サマリーを返す"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS total, "
            "COUNT(CASE WHEN outcome IS NOT NULL THEN 1 END) AS resolved "
            "FROM predictions"
        ).fetchone()
        return {"total": row[0], "resolved": row[1], "pending": row[0] - row[1]}

    def get_brier_score(self, since: date = None) -> Optional[float]:
        query = "SELECT AVG(brier_score) FROM predictions WHERE brier_score IS NOT NULL"
        params = []
        if since:
            query += " AND outcome_date >= ?"
            params.append(since)
        row = self.conn.execute(query, params).fetchone()
        return row[0] if row and row[0] is not None else None

    def get_calibration_data(self) -> list[dict]:
        return self.conn.execute("""
            SELECT
                FLOOR(confidence * 10) / 10 AS bucket,
                COUNT(*) AS n,
                AVG(CASE WHEN outcome THEN 1.0 ELSE 0.0 END) AS hit_rate,
                AVG(confidence) AS avg_confidence
            FROM predictions
            WHERE outcome IS NOT NULL
            GROUP BY bucket
            ORDER BY bucket
        """).fetchdf().to_dict("records")

    # ── market_observations ──

    def add_observation(
        self,
        dt: date,
        series: str,
        value: float,
        source: str,
        observed_at: datetime,
    ):
        """手動マクロデータ投入（ADR-005）

        ADR-003 Write基準: ソース明記が必須。
        同じ(date, series, source)のデータはupsert。
        """
        _require_aware(observed_at, "observed_at")
        self.conn.execute(
            "DELETE FROM market_observations WHERE date = ? AND series = ? AND source = ?",
            [dt, series, source],
        )
        self.conn.execute("""
            INSERT INTO market_observations (date, series, value, source, observed_at)
            VALUES (?, ?, ?, ?, ?)
        """, [dt, series, value, source, observed_at])

    def get_latest_observations(self) -> list[dict]:
        """各シリーズの最新の観測値を取得（ソース問わず最新日のもの）"""
        return self.conn.execute("""
            SELECT o.date, o.series, o.value, o.source, o.status
            FROM market_observations o
            INNER JOIN (
                SELECT series, MAX(date) AS max_date
                FROM market_observations
                GROUP BY series
            ) latest ON o.series = latest.series AND o.date = latest.max_date
            ORDER BY o.series
        """).fetchdf().to_dict("records")

    def get_observations_for_date(self, dt: date) -> list[dict]:
        return self.conn.execute(
            "SELECT * FROM market_observations WHERE date = ? ORDER BY series",
            [dt],
        ).fetchdf().to_dict("records")

    def verify_observation(self, dt: date, series: str, source: str):
        self.conn.execute(
            "UPDATE market_observations SET status = 'verified' WHERE date = ? AND series = ? AND source = ?",
            [dt, series, source],
        )

    # ── knowledge ──

    def add_knowledge(
        self,
        knowledge_id: str,
        category: str,
        content: str,
        evidence: str,
        *,
        confidence: str = "low",
        discovered_date: date = None,
    ) -> str:
        if discovered_date is None:
            discovered_date = date.today()

        existing = self.conn.execute(
            "SELECT id FROM knowledge WHERE id = ?", [knowledge_id]
        ).fetchone()
        if existing:
            self.conn.execute("""
                UPDATE knowledge SET content = ?, evidence = ?, confidence = ?, last_verified_date = ?
                WHERE id = ?
            """, [content, evidence, confidence, date.today(), knowledge_id])
            return knowledge_id

        self.conn.execute("""
            INSERT INTO knowledge (id, category, content, evidence, confidence, discovered_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [knowledge_id, category, content, evidence, confidence, discovered_date])
        return knowledge_id

    def update_knowledge_status(self, knowledge_id: str, status: str, reason: str = None):
        valid = {"hypothesis", "tested", "validated", "invalidated"}
        if status not in valid:
            raise ValueError(f"status must be one of {valid}")
        params = [status, date.today()]
        query = "UPDATE knowledge SET verification_status = ?, last_verified_date = ?"
        if status == "invalidated" and reason:
            query += ", invalidation_reason = ?"
            params.append(reason)
        query += " WHERE id = ?"
        params.append(knowledge_id)
        self.conn.execute(query, params)

    def get_active_knowledge(self) -> list[dict]:
        return self.conn.execute(
            "SELECT * FROM knowledge WHERE verification_status != 'invalidated' ORDER BY category, id"
        ).fetchdf().to_dict("records")

    def get_stale_knowledge(self, days: int = 180) -> list[dict]:
        return self.conn.execute(f"""
            SELECT * FROM knowledge
            WHERE verification_status NOT IN ('invalidated')
            AND (last_verified_date IS NULL OR last_verified_date < current_date - INTERVAL '{days} days')
            ORDER BY last_verified_date
        """).fetchdf().to_dict("records")

    # ── regime_assessments ──

    def save_regime(
        self,
        dt: date,
        *,
        vix_regime: str = None,
        vix_term_structure: str = None,
        credit_regime: str = None,
        yield_curve_regime: str = None,
        oil_regime: str = None,
        dollar_regime: str = None,
        overall: str = None,
        reasoning: str = None,
    ):
        self.conn.execute("DELETE FROM regime_assessments WHERE date = ?", [dt])
        self.conn.execute("""
            INSERT INTO regime_assessments
                (date, vix_regime, vix_term_structure, credit_regime, yield_curve_regime,
                 oil_regime, dollar_regime, overall, reasoning)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [dt, vix_regime, vix_term_structure, credit_regime, yield_curve_regime,
              oil_regime, dollar_regime, overall, reasoning])

    def get_latest_regime(self) -> Optional[dict]:
        rows = self.conn.execute(
            "SELECT * FROM regime_assessments ORDER BY date DESC LIMIT 1"
        ).fetchdf().to_dict("records")
        return rows[0] if rows else None

    # ── event_reviews ──

    def add_event_review(
        self,
        event_id: int,
        review_date: date,
        original_impact: str,
        revised_impact: str,
        actual_outcome: str,
        lesson: str,
    ):
        self.conn.execute(
            "DELETE FROM event_reviews WHERE event_id = ? AND review_date = ?",
            [event_id, review_date],
        )
        self.conn.execute("""
            INSERT INTO event_reviews (event_id, review_date, original_impact, revised_impact, actual_outcome, lesson)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [event_id, review_date, original_impact, revised_impact, actual_outcome, lesson])
        self.update_event_status(event_id, "reviewed")

    # ── self-evaluation ──

    def get_bias_check(self) -> dict:
        """Charter 4.3: バイアス検出用データを返す"""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE outcome IS NOT NULL"
        ).fetchone()[0]
        if total == 0:
            return {"total": 0, "message": "予測データ不足。判定不可"}

        bullish = self.conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE outcome IS NOT NULL AND confidence > 0.5"
        ).fetchone()[0]
        bullish_pct = bullish / total * 100

        high_conf = self.conn.execute("""
            SELECT COUNT(*) AS n,
                   AVG(CASE WHEN outcome THEN 1.0 ELSE 0.0 END) AS hit_rate
            FROM predictions
            WHERE outcome IS NOT NULL AND confidence >= 0.8
        """).fetchone()

        recent_brier = self.conn.execute("""
            SELECT AVG(brier_score) FROM (
                SELECT brier_score FROM predictions
                WHERE brier_score IS NOT NULL
                ORDER BY outcome_date DESC LIMIT 5
            )
        """).fetchone()[0]

        overall_brier = self.get_brier_score()

        return {
            "total": total,
            "bullish_pct": bullish_pct,
            "confirmation_bias_flag": bullish_pct > 65 or bullish_pct < 35,
            "high_conf_n": high_conf[0] if high_conf else 0,
            "high_conf_hit_rate": high_conf[1] if high_conf else None,
            "overconfidence_flag": (high_conf[1] or 0) < 0.8 if high_conf and high_conf[0] >= 5 else None,
            "recent_brier": recent_brier,
            "overall_brier": overall_brier,
            "recency_bias_flag": abs((recent_brier or 0) - (overall_brier or 0)) > 0.1 if recent_brier and overall_brier else None,
        }
