"""Learning system DuckDB schema and CRUD (ADR-023).

This module is fully independent of the parent Master Sensei codebase.
It uses its own DuckDB file `learning/data/drill.duckdb`, with no
cross-dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import duckdb

from learning.timeutil import _require_aware, now_jst, today_jst


@dataclass
class Question:
    id: str
    stage: int
    category: str
    term: str
    question_type: str  # recall | mcq | application
    prompt: str
    rubric: list[str]
    explanation: str
    mcq_choices: Optional[list[str]] = None
    correct_choice: Optional[str] = None
    prereqs: Optional[list[str]] = None
    difficulty: int = 1
    source_file: Optional[str] = None


@dataclass
class Mastery:
    question_id: str
    leitner_box: int
    next_due_date: date
    consecutive_correct: int
    total_attempts: int
    total_correct: int
    last_attempt_at: Optional[datetime]
    first_seen_at: datetime


class LearningDB:
    """CRUD for learning_questions / learning_attempts / learning_mastery."""

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self.conn = conn
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_questions (
                id VARCHAR PRIMARY KEY,
                stage INTEGER NOT NULL,
                category VARCHAR NOT NULL,
                term VARCHAR NOT NULL,
                question_type VARCHAR NOT NULL,
                prompt TEXT NOT NULL,
                rubric TEXT NOT NULL,
                mcq_choices TEXT,
                correct_choice VARCHAR,
                explanation TEXT NOT NULL,
                prereqs VARCHAR[],
                difficulty INTEGER DEFAULT 1,
                source_file VARCHAR,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """
        )

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_attempts (
                attempt_id INTEGER PRIMARY KEY,
                question_id VARCHAR NOT NULL,
                attempted_at TIMESTAMPTZ NOT NULL,
                user_answer TEXT,
                self_rating VARCHAR NOT NULL,
                outcome VARCHAR NOT NULL,
                time_spent_seconds INTEGER,
                notes TEXT
            )
            """
        )
        self.conn.execute(
            "CREATE SEQUENCE IF NOT EXISTS learning_attempts_id_seq START 1"
        )

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_mastery (
                question_id VARCHAR PRIMARY KEY,
                leitner_box INTEGER NOT NULL DEFAULT 1,
                next_due_date DATE NOT NULL,
                consecutive_correct INTEGER NOT NULL DEFAULT 0,
                total_attempts INTEGER NOT NULL DEFAULT 0,
                total_correct INTEGER NOT NULL DEFAULT 0,
                last_attempt_at TIMESTAMPTZ,
                first_seen_at TIMESTAMPTZ DEFAULT current_timestamp
            )
            """
        )

    # -------- Questions CRUD --------

    def upsert_question(self, q: Question) -> None:
        import json

        rubric_json = json.dumps(q.rubric, ensure_ascii=False)
        mcq_json = (
            json.dumps(q.mcq_choices, ensure_ascii=False) if q.mcq_choices else None
        )
        self.conn.execute(
            """
            INSERT INTO learning_questions
              (id, stage, category, term, question_type, prompt, rubric,
               mcq_choices, correct_choice, explanation, prereqs, difficulty,
               source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
              stage = excluded.stage,
              category = excluded.category,
              term = excluded.term,
              question_type = excluded.question_type,
              prompt = excluded.prompt,
              rubric = excluded.rubric,
              mcq_choices = excluded.mcq_choices,
              correct_choice = excluded.correct_choice,
              explanation = excluded.explanation,
              prereqs = excluded.prereqs,
              difficulty = excluded.difficulty,
              source_file = excluded.source_file
            """,
            [
                q.id,
                q.stage,
                q.category,
                q.term,
                q.question_type,
                q.prompt,
                rubric_json,
                mcq_json,
                q.correct_choice,
                q.explanation,
                q.prereqs or [],
                q.difficulty,
                q.source_file,
            ],
        )

    def get_question(self, qid: str) -> Optional[Question]:
        import json

        row = self.conn.execute(
            "SELECT id, stage, category, term, question_type, prompt, rubric, "
            "mcq_choices, correct_choice, explanation, prereqs, difficulty, "
            "source_file FROM learning_questions WHERE id = ?",
            [qid],
        ).fetchone()
        if not row:
            return None
        return Question(
            id=row[0],
            stage=row[1],
            category=row[2],
            term=row[3],
            question_type=row[4],
            prompt=row[5],
            rubric=json.loads(row[6]),
            mcq_choices=json.loads(row[7]) if row[7] else None,
            correct_choice=row[8],
            explanation=row[9],
            prereqs=list(row[10]) if row[10] else None,
            difficulty=row[11],
            source_file=row[12],
        )

    def list_questions_by_stage(self, stage: int) -> list[Question]:
        rows = self.conn.execute(
            "SELECT id FROM learning_questions WHERE stage = ? ORDER BY id",
            [stage],
        ).fetchall()
        return [self.get_question(r[0]) for r in rows]  # type: ignore[misc]

    # -------- Mastery CRUD --------

    def get_mastery(self, qid: str) -> Optional[Mastery]:
        row = self.conn.execute(
            "SELECT question_id, leitner_box, next_due_date, consecutive_correct, "
            "total_attempts, total_correct, last_attempt_at, first_seen_at "
            "FROM learning_mastery WHERE question_id = ?",
            [qid],
        ).fetchone()
        if not row:
            return None
        return Mastery(
            question_id=row[0],
            leitner_box=row[1],
            next_due_date=row[2],
            consecutive_correct=row[3],
            total_attempts=row[4],
            total_correct=row[5],
            last_attempt_at=row[6],
            first_seen_at=row[7],
        )

    def init_mastery(self, qid: str) -> Mastery:
        """Create a Box-1 mastery row due today."""
        today = today_jst()
        self.conn.execute(
            "INSERT INTO learning_mastery "
            "(question_id, leitner_box, next_due_date) VALUES (?, 1, ?) "
            "ON CONFLICT (question_id) DO NOTHING",
            [qid, today],
        )
        m = self.get_mastery(qid)
        assert m is not None
        return m

    def update_mastery(
        self,
        qid: str,
        new_box: int,
        next_due: date,
        consecutive_correct: int,
        total_attempts_delta: int,
        total_correct_delta: int,
        now: datetime,
    ) -> None:
        _require_aware(now, "now")
        self.conn.execute(
            "UPDATE learning_mastery SET "
            "  leitner_box = ?, next_due_date = ?, consecutive_correct = ?, "
            "  total_attempts = total_attempts + ?, "
            "  total_correct = total_correct + ?, "
            "  last_attempt_at = ? "
            "WHERE question_id = ?",
            [
                new_box,
                next_due,
                consecutive_correct,
                total_attempts_delta,
                total_correct_delta,
                now,
                qid,
            ],
        )

    # -------- Attempts --------

    def record_attempt(
        self,
        question_id: str,
        user_answer: Optional[str],
        self_rating: str,  # A | B | C
        outcome: str,  # correct | partial | wrong
        time_spent_seconds: Optional[int] = None,
        notes: Optional[str] = None,
        attempted_at: Optional[datetime] = None,
    ) -> int:
        at = attempted_at or now_jst()
        _require_aware(at, "attempted_at")
        if self_rating not in {"A", "B", "C"}:
            raise ValueError(f"self_rating must be A/B/C, got {self_rating}")
        if outcome not in {"correct", "partial", "wrong"}:
            raise ValueError(f"outcome invalid: {outcome}")
        attempt_id = self.conn.execute(
            "SELECT nextval('learning_attempts_id_seq')"
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO learning_attempts "
            "(attempt_id, question_id, attempted_at, user_answer, self_rating, "
            " outcome, time_spent_seconds, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                attempt_id,
                question_id,
                at,
                user_answer,
                self_rating,
                outcome,
                time_spent_seconds,
                notes,
            ],
        )
        return attempt_id

    # -------- Queries for CLI --------

    def due_questions(self, today: date, limit: int = 10) -> list[Question]:
        """Questions with next_due_date <= today, ordered by box asc then due date."""
        rows = self.conn.execute(
            "SELECT m.question_id FROM learning_mastery m "
            "WHERE m.next_due_date <= ? "
            "ORDER BY m.leitner_box ASC, m.next_due_date ASC "
            "LIMIT ?",
            [today, limit],
        ).fetchall()
        return [self.get_question(r[0]) for r in rows]  # type: ignore[misc]

    def unseen_questions(self, stage: int, limit: int = 3) -> list[Question]:
        """Questions in stage that have no mastery row yet (never seen)."""
        rows = self.conn.execute(
            "SELECT q.id FROM learning_questions q "
            "LEFT JOIN learning_mastery m ON q.id = m.question_id "
            "WHERE m.question_id IS NULL AND q.stage = ? "
            "ORDER BY q.difficulty ASC, q.id ASC "
            "LIMIT ?",
            [stage, limit],
        ).fetchall()
        return [self.get_question(r[0]) for r in rows]  # type: ignore[misc]

    def mastery_summary(self) -> dict:
        """Summary stats for /learn-status."""
        total_q = self.conn.execute(
            "SELECT COUNT(*) FROM learning_questions"
        ).fetchone()[0]
        seen = self.conn.execute(
            "SELECT COUNT(*) FROM learning_mastery"
        ).fetchone()[0]
        box_dist = {
            row[0]: row[1]
            for row in self.conn.execute(
                "SELECT leitner_box, COUNT(*) FROM learning_mastery GROUP BY 1"
            ).fetchall()
        }
        mastered = box_dist.get(5, 0)
        stage_breakdown = self.conn.execute(
            "SELECT q.stage, COUNT(m.question_id) "
            "FROM learning_questions q "
            "LEFT JOIN learning_mastery m ON q.id = m.question_id "
            "GROUP BY q.stage ORDER BY q.stage"
        ).fetchall()
        return {
            "total_questions": total_q,
            "seen": seen,
            "mastered": mastered,
            "box_distribution": box_dist,
            "stage_breakdown": stage_breakdown,
        }

    def recent_attempts(self, limit: int = 20) -> list[tuple]:
        return self.conn.execute(
            "SELECT a.attempt_id, a.question_id, q.term, a.attempted_at, "
            "  a.self_rating, a.outcome "
            "FROM learning_attempts a JOIN learning_questions q "
            "  ON a.question_id = q.id "
            "ORDER BY a.attempted_at DESC LIMIT ?",
            [limit],
        ).fetchall()

    def weak_terms(self, min_attempts: int = 3) -> list[tuple]:
        """Terms with high wrong rate among those attempted at least min_attempts times."""
        return self.conn.execute(
            "SELECT q.term, COUNT(*) AS attempts, "
            "  SUM(CASE WHEN a.outcome = 'wrong' THEN 1 ELSE 0 END) AS wrongs, "
            "  ROUND(AVG(CASE WHEN a.outcome = 'correct' THEN 1.0 "
            "    WHEN a.outcome = 'partial' THEN 0.5 ELSE 0.0 END), 2) AS score "
            "FROM learning_attempts a JOIN learning_questions q "
            "  ON a.question_id = q.id "
            "GROUP BY q.term "
            "HAVING attempts >= ? "
            "ORDER BY score ASC, attempts DESC",
            [min_attempts],
        ).fetchall()
