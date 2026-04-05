"""Master Sensei DuckDBスキーマ定義・CRUD操作

テーブル:
- events: マクロイベント記録（source列で登録経路を識別）
- predictions: 予測記録（Brier score計測用）
- knowledge: 知見DB（パターン・ルール蓄積）
- regime_assessments: レジーム判定（入力値スナップショット含む、ADR-009）
- event_reviews: イベント事後検証
- skill_executions: スキル実行履歴（Airflow dag_runパターン）
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import duckdb

JST = timezone(offset=__import__("datetime").timedelta(hours=9))


def now_jst() -> datetime:
    """現在時刻をJSTで取得（分精度）。システムTZに依存しない。"""
    return datetime.now(tz=JST)


def today_jst() -> date:
    """JSTの「今日」を取得。システムTZに依存しない。"""
    return datetime.now(tz=JST).date()


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
                source VARCHAR DEFAULT 'manual',
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
                category VARCHAR DEFAULT 'market',
                root_cause_category VARCHAR
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
                source_prediction_id INTEGER,
                tldr VARCHAR,
                related_knowledge_ids VARCHAR[],
                created_at TIMESTAMP DEFAULT current_timestamp
            )
        """)
        # ADR-020 migration: add columns if missing (for existing DBs)
        existing_cols = {
            row[0] for row in self.conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'knowledge' AND table_schema = 'main'"
            ).fetchall()
        }
        if "tldr" not in existing_cols:
            self.conn.execute("ALTER TABLE knowledge ADD COLUMN tldr VARCHAR")
        if "related_knowledge_ids" not in existing_cols:
            self.conn.execute("ALTER TABLE knowledge ADD COLUMN related_knowledge_ids VARCHAR[]")

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
                vix_value DOUBLE,
                vix3m_value DOUBLE,
                hy_spread_value DOUBLE,
                yield_curve_value DOUBLE,
                oil_value DOUBLE,
                usd_value DOUBLE,
                created_at TIMESTAMP DEFAULT current_timestamp
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

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_executions (
                id INTEGER PRIMARY KEY,
                skill_name VARCHAR NOT NULL,
                executed_at TIMESTAMPTZ NOT NULL,
                result_summary VARCHAR,
                metadata VARCHAR,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
        """)
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS skill_executions_id_seq START 1")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY,
                instrument VARCHAR NOT NULL,
                direction VARCHAR NOT NULL,
                entry_date DATE NOT NULL,
                entry_price DOUBLE NOT NULL,
                exit_date DATE,
                exit_price DOUBLE,
                quantity INTEGER NOT NULL,
                pnl_usd DOUBLE,
                pnl_pct DOUBLE,
                commission_usd DOUBLE,
                holding_days INTEGER,
                regime_at_entry VARCHAR,
                vix_at_entry DOUBLE,
                brent_at_entry DOUBLE,
                confidence_at_entry DOUBLE,
                setup_type VARCHAR,
                entry_reasoning TEXT,
                exit_reasoning TEXT,
                discipline_score INTEGER,
                review_notes TEXT,
                prediction_id INTEGER,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
        """)
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS trades_id_seq START 1")

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
        source: str = "manual",
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
            INSERT INTO events (id, event_timestamp, category, summary, impact, impact_reasoning, relevance, source_url, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [event_id, event_timestamp, category, summary, impact, impact_reasoning, relevance, source_url, source])
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
        root_cause_category: str = None,
    ):
        row = self.conn.execute("SELECT confidence FROM predictions WHERE id = ?", [pred_id]).fetchone()
        if not row:
            raise ValueError(f"Prediction {pred_id} not found")
        confidence = row[0]
        brier = (confidence - (1.0 if outcome else 0.0)) ** 2

        self.conn.execute("""
            UPDATE predictions
            SET outcome = ?, outcome_date = ?, outcome_notes = ?, brier_score = ?, root_cause_category = ?
            WHERE id = ?
        """, [outcome, outcome_date, outcome_notes, brier, root_cause_category, pred_id])

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

    def get_brier_decomposition(self) -> dict:
        """Murphy (1973) Brier Score 3成分分解

        Brier = Reliability - Resolution + Uncertainty
        - Reliability: 較正誤差（小さいほど良い）
        - Resolution: 情報弁別力（大きいほど良い）
        - Uncertainty: 基準分散（データ固有、制御不能）
        """
        rows = self.conn.execute("""
            SELECT confidence, outcome FROM predictions WHERE outcome IS NOT NULL
        """).fetchall()
        if not rows:
            return {"brier_score": None, "reliability": None, "resolution": None, "uncertainty": None, "n": 0}

        n = len(rows)
        outcomes = [1.0 if r[1] else 0.0 for r in rows]
        forecasts = [r[0] for r in rows]
        base_rate = sum(outcomes) / n

        # Uncertainty: base_rate * (1 - base_rate)
        uncertainty = base_rate * (1 - base_rate)

        # Bin forecasts into 10 buckets (0.0-0.1, ..., 0.9-1.0)
        bins: dict[int, list[tuple[float, float]]] = {}
        for f, o in zip(forecasts, outcomes):
            bucket = min(int(f * 10), 9)
            bins.setdefault(bucket, []).append((f, o))

        reliability = 0.0
        resolution = 0.0
        for bucket, items in bins.items():
            nk = len(items)
            avg_forecast = sum(f for f, _ in items) / nk
            avg_outcome = sum(o for _, o in items) / nk
            reliability += nk * (avg_forecast - avg_outcome) ** 2
            resolution += nk * (avg_outcome - base_rate) ** 2

        reliability /= n
        resolution /= n

        brier = sum((f - o) ** 2 for f, o in zip(forecasts, outcomes)) / n

        return {
            "brier_score": brier,
            "reliability": reliability,
            "resolution": resolution,
            "uncertainty": uncertainty,
            "n": n,
        }

    def get_baseline_score(self) -> dict:
        """50%無情報ベースラインとの比較（Metaculus方式）

        skill_score > 0: ベースラインより良い
        skill_score < 0: コイン投げ以下
        """
        rows = self.conn.execute("""
            SELECT confidence, outcome FROM predictions WHERE outcome IS NOT NULL
        """).fetchall()
        if not rows:
            return {"brier_score": None, "baseline_brier": None, "skill_score": None, "n": 0}

        n = len(rows)
        brier = sum((r[0] - (1.0 if r[1] else 0.0)) ** 2 for r in rows) / n
        baseline_brier = 0.25  # 常に50%と予測した場合のBrier score

        return {
            "brier_score": brier,
            "baseline_brier": baseline_brier,
            "skill_score": baseline_brier - brier,  # 正なら良い
            "n": n,
        }

    def get_kolb_cycle_rate(self) -> dict:
        """Kolbサイクル完遂率: 解決済み予測のうち知見に連鎖したものの割合"""
        resolved = self.conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE outcome IS NOT NULL"
        ).fetchone()[0]
        with_knowledge = self.conn.execute(
            "SELECT COUNT(DISTINCT source_prediction_id) FROM knowledge WHERE source_prediction_id IS NOT NULL"
        ).fetchone()[0]

        return {
            "resolved": resolved,
            "with_knowledge": with_knowledge,
            "completion_rate": with_knowledge / resolved if resolved > 0 else 0.0,
        }

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
        source_prediction_id: int = None,
        tldr: str = None,
        related_knowledge_ids: list[str] = None,
    ) -> str:
        if discovered_date is None:
            discovered_date = today_jst()

        existing = self.conn.execute(
            "SELECT id FROM knowledge WHERE id = ?", [knowledge_id]
        ).fetchone()
        if existing:
            self.conn.execute("""
                UPDATE knowledge SET content = ?, evidence = ?, confidence = ?,
                    last_verified_date = ?, source_prediction_id = COALESCE(?, source_prediction_id),
                    tldr = COALESCE(?, tldr),
                    related_knowledge_ids = COALESCE(?, related_knowledge_ids)
                WHERE id = ?
            """, [content, evidence, confidence, today_jst(), source_prediction_id,
                  tldr, related_knowledge_ids, knowledge_id])
            return knowledge_id

        self.conn.execute("""
            INSERT INTO knowledge (id, category, content, evidence, confidence, discovered_date,
                                   source_prediction_id, tldr, related_knowledge_ids)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [knowledge_id, category, content, evidence, confidence, discovered_date,
              source_prediction_id, tldr, related_knowledge_ids])
        return knowledge_id

    def get_backlinks(self, knowledge_id: str) -> list[dict]:
        """Return all knowledge entries referencing knowledge_id (ADR-020)."""
        return self.conn.execute("""
            SELECT * FROM knowledge
            WHERE list_contains(related_knowledge_ids, ?)
            ORDER BY id
        """, [knowledge_id]).fetchdf().to_dict("records")

    def update_knowledge_status(self, knowledge_id: str, status: str, reason: str = None):
        valid = {"hypothesis", "tested", "validated", "invalidated"}
        if status not in valid:
            raise ValueError(f"status must be one of {valid}")
        params = [status, today_jst()]
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
        vix_value: float = None,
        vix3m_value: float = None,
        hy_spread_value: float = None,
        yield_curve_value: float = None,
        oil_value: float = None,
        usd_value: float = None,
    ):
        self.conn.execute("DELETE FROM regime_assessments WHERE date = ?", [dt])
        self.conn.execute("""
            INSERT INTO regime_assessments
                (date, vix_regime, vix_term_structure, credit_regime, yield_curve_regime,
                 oil_regime, dollar_regime, overall, reasoning,
                 vix_value, vix3m_value, hy_spread_value, yield_curve_value, oil_value, usd_value)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [dt, vix_regime, vix_term_structure, credit_regime, yield_curve_regime,
              oil_regime, dollar_regime, overall, reasoning,
              vix_value, vix3m_value, hy_spread_value, yield_curve_value, oil_value, usd_value])

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

    def get_impact_lessons(self, limit: int = 5) -> list[dict]:
        """impact修正があったレビューを取得する（過去の判定ミスから学ぶ用）"""
        rows = self.conn.execute(
            "SELECT e.category, e.summary, er.original_impact, er.revised_impact, er.lesson "
            "FROM event_reviews er "
            "JOIN events e ON er.event_id = e.id "
            "WHERE er.original_impact != er.revised_impact "
            "ORDER BY er.review_date DESC LIMIT ?",
            [limit],
        ).fetchdf().to_dict("records")
        return rows

    # ── skill_executions ──

    def record_skill_execution(
        self,
        skill_name: str,
        executed_at: datetime,
        result_summary: str = None,
        metadata: str = None,
    ) -> int:
        _require_aware(executed_at, "executed_at")
        exec_id = self.conn.execute("SELECT nextval('skill_executions_id_seq')").fetchone()[0]
        self.conn.execute("""
            INSERT INTO skill_executions (id, skill_name, executed_at, result_summary, metadata)
            VALUES (?, ?, ?, ?, ?)
        """, [exec_id, skill_name, executed_at, result_summary, metadata])
        return exec_id

    def get_last_skill_execution(self, skill_name: str) -> Optional[dict]:
        rows = self.conn.execute(
            "SELECT * FROM skill_executions WHERE skill_name = ? ORDER BY executed_at DESC LIMIT 1",
            [skill_name],
        ).fetchdf().to_dict("records")
        return rows[0] if rows else None

    # ── trades (ADR-015) ──

    def add_trade(
        self,
        instrument: str,
        direction: str,
        entry_date: date,
        entry_price: float,
        quantity: int,
        *,
        regime_at_entry: str = None,
        vix_at_entry: float = None,
        brent_at_entry: float = None,
        confidence_at_entry: float = None,
        setup_type: str = None,
        entry_reasoning: str = None,
        prediction_id: int = None,
    ) -> int:
        if confidence_at_entry is not None and not (0.0 <= confidence_at_entry <= 1.0):
            raise ValueError("confidence_at_entry must be 0.0-1.0")
        tid = self.conn.execute("SELECT nextval('trades_id_seq')").fetchone()[0]
        self.conn.execute(
            "INSERT INTO trades "
            "(id, instrument, direction, entry_date, entry_price, quantity, "
            "regime_at_entry, vix_at_entry, brent_at_entry, confidence_at_entry, "
            "setup_type, entry_reasoning, prediction_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [tid, instrument, direction, entry_date, entry_price, quantity,
             regime_at_entry, vix_at_entry, brent_at_entry, confidence_at_entry,
             setup_type, entry_reasoning, prediction_id],
        )
        return tid

    def close_trade(
        self,
        trade_id: int,
        exit_date: date,
        exit_price: float,
        *,
        exit_reasoning: str = None,
        commission_usd: float = None,
    ):
        row = self.conn.execute(
            "SELECT entry_price, quantity, direction, entry_date FROM trades WHERE id = ?",
            [trade_id],
        ).fetchone()
        if row is None:
            raise ValueError(f"Trade {trade_id} not found")
        entry_price, quantity, direction, entry_dt = row
        if direction == "long":
            pnl_usd = (exit_price - entry_price) * quantity
        else:
            pnl_usd = (entry_price - exit_price) * quantity
        pnl_pct = (pnl_usd / (entry_price * quantity)) * 100
        holding_days = (exit_date - entry_dt).days
        self.conn.execute(
            "UPDATE trades SET exit_date = ?, exit_price = ?, pnl_usd = ?, pnl_pct = ?, "
            "commission_usd = ?, holding_days = ?, exit_reasoning = ? WHERE id = ?",
            [exit_date, exit_price, pnl_usd, pnl_pct, commission_usd, holding_days,
             exit_reasoning, trade_id],
        )

    def review_trade(
        self,
        trade_id: int,
        discipline_score: int = None,
        review_notes: str = None,
    ):
        if discipline_score is not None and not (1 <= discipline_score <= 5):
            raise ValueError("discipline_score must be 1-5")
        self.conn.execute(
            "UPDATE trades SET discipline_score = ?, review_notes = ? WHERE id = ?",
            [discipline_score, review_notes, trade_id],
        )

    def get_open_trades(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM trades WHERE exit_date IS NULL ORDER BY entry_date"
        ).fetchdf().to_dict("records")
        return rows

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
