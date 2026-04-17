"""Tests for the learning drill system (ADR-023, ADR-005)."""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import duckdb
import pytest

from learning.db import LearningDB, Question
from learning.loader import parse_question_file, load_all_questions
from learning.scheduler import BOX_INTERVALS, LeitnerScheduler
from learning.timeutil import today_jst


JST = timezone(timedelta(hours=9))


# ========== Scheduler ==========


def test_scheduler_correct_answer_advances_box():
    today = date(2026, 4, 16)
    d = LeitnerScheduler.schedule_next(
        current_box=1,
        outcome="correct",
        current_consecutive_correct=0,
        today=today,
    )
    assert d.new_box == 2
    assert d.consecutive_correct == 1
    assert d.next_due_date == today + timedelta(days=BOX_INTERVALS[2])


def test_scheduler_correct_answer_caps_at_box_5():
    today = date(2026, 4, 16)
    d = LeitnerScheduler.schedule_next(
        current_box=5,
        outcome="correct",
        current_consecutive_correct=1,
        today=today,
    )
    assert d.new_box == 5
    assert d.consecutive_correct == 2
    assert d.next_due_date == today + timedelta(days=16)


def test_scheduler_wrong_answer_resets_to_box_1():
    today = date(2026, 4, 16)
    d = LeitnerScheduler.schedule_next(
        current_box=4,
        outcome="wrong",
        current_consecutive_correct=3,
        today=today,
    )
    assert d.new_box == 1
    assert d.consecutive_correct == 0
    assert d.next_due_date == today + timedelta(days=1)


def test_scheduler_partial_holds_box_but_resets_streak():
    today = date(2026, 4, 16)
    d = LeitnerScheduler.schedule_next(
        current_box=3,
        outcome="partial",
        current_consecutive_correct=2,
        today=today,
    )
    assert d.new_box == 3
    assert d.consecutive_correct == 0
    assert d.next_due_date == today + timedelta(days=BOX_INTERVALS[3])


def test_scheduler_rejects_invalid_outcome():
    with pytest.raises(ValueError, match="outcome"):
        LeitnerScheduler.schedule_next(
            current_box=1,
            outcome="xxx",
            current_consecutive_correct=0,
            today=date(2026, 4, 16),
        )


def test_scheduler_rejects_out_of_range_box():
    with pytest.raises(ValueError, match="box"):
        LeitnerScheduler.schedule_next(
            current_box=6,
            outcome="correct",
            current_consecutive_correct=0,
            today=date(2026, 4, 16),
        )


def test_mastered_requires_box_5_and_2_consecutive():
    assert not LeitnerScheduler.is_mastered(5, 1)
    assert LeitnerScheduler.is_mastered(5, 2)
    assert LeitnerScheduler.is_mastered(5, 3)
    assert not LeitnerScheduler.is_mastered(4, 10)


# ========== DB ==========


@pytest.fixture
def db():
    conn = duckdb.connect(":memory:")
    conn.execute("SET TIMEZONE = 'Asia/Tokyo'")
    return LearningDB(conn)


def _sample_question(qid="Q-TEST-01", stage=1, term="テスト用語") -> Question:
    return Question(
        id=qid,
        stage=stage,
        category="basic",
        term=term,
        question_type="mcq",
        prompt="テスト質問",
        rubric=["keyword1", "keyword2"],
        explanation="テスト解説",
        mcq_choices=["A. 正解", "B. 不正解1", "C. 不正解2", "D. 不正解3"],
        correct_choice="A",
        difficulty=1,
    )


def test_db_upsert_and_get_question(db):
    q = _sample_question()
    db.upsert_question(q)
    got = db.get_question("Q-TEST-01")
    assert got is not None
    assert got.term == "テスト用語"
    assert got.rubric == ["keyword1", "keyword2"]


def test_db_upsert_updates_existing_question(db):
    q = _sample_question()
    db.upsert_question(q)
    q2 = _sample_question(qid="Q-TEST-01", term="更新後用語")
    db.upsert_question(q2)
    got = db.get_question("Q-TEST-01")
    assert got.term == "更新後用語"


def test_db_init_mastery_creates_box_1(db):
    db.upsert_question(_sample_question())
    m = db.init_mastery("Q-TEST-01")
    assert m.leitner_box == 1
    assert m.total_attempts == 0
    assert m.total_correct == 0


def test_db_record_attempt_mcq_auto(db):
    db.upsert_question(_sample_question())
    db.init_mastery("Q-TEST-01")
    now = datetime.now(tz=JST)
    aid = db.record_attempt(
        "Q-TEST-01", "A", "correct",
        grading_method="mcq_auto",
        attempted_at=now,
    )
    row = db.conn.execute(
        "SELECT self_rating, grading_method, outcome "
        "FROM learning_attempts WHERE attempt_id = ?",
        [aid],
    ).fetchone()
    assert row[0] is None
    assert row[1] == "mcq_auto"
    assert row[2] == "correct"


def test_db_record_attempt_self_rating(db):
    db.upsert_question(_sample_question())
    db.init_mastery("Q-TEST-01")
    now = datetime.now(tz=JST)
    aid = db.record_attempt(
        "Q-TEST-01", "answer text", "correct",
        grading_method="self",
        self_rating="A",
        attempted_at=now,
    )
    row = db.conn.execute(
        "SELECT self_rating, grading_method FROM learning_attempts WHERE attempt_id = ?",
        [aid],
    ).fetchone()
    assert row[0] == "A"
    assert row[1] == "self"


def test_db_record_attempt_returns_sequential_ids(db):
    db.upsert_question(_sample_question())
    db.init_mastery("Q-TEST-01")
    now = datetime.now(tz=JST)
    id1 = db.record_attempt(
        "Q-TEST-01", "A", "correct",
        grading_method="mcq_auto", attempted_at=now,
    )
    id2 = db.record_attempt(
        "Q-TEST-01", "B", "wrong",
        grading_method="mcq_auto", attempted_at=now,
    )
    assert id2 == id1 + 1


def test_db_record_attempt_rejects_invalid_rating(db):
    db.upsert_question(_sample_question())
    db.init_mastery("Q-TEST-01")
    with pytest.raises(ValueError, match="self_rating"):
        db.record_attempt(
            "Q-TEST-01", "ans", "correct",
            grading_method="self", self_rating="Z",
            attempted_at=datetime.now(tz=JST),
        )


def test_db_record_attempt_rejects_invalid_grading_method(db):
    db.upsert_question(_sample_question())
    db.init_mastery("Q-TEST-01")
    with pytest.raises(ValueError, match="grading_method"):
        db.record_attempt(
            "Q-TEST-01", "ans", "correct",
            grading_method="invalid",
            attempted_at=datetime.now(tz=JST),
        )


def test_db_update_mastery_increments_totals(db):
    db.upsert_question(_sample_question())
    db.init_mastery("Q-TEST-01")
    now = datetime.now(tz=JST)
    db.update_mastery(
        qid="Q-TEST-01",
        new_box=2,
        next_due=date(2026, 4, 20),
        consecutive_correct=1,
        total_attempts_delta=1,
        total_correct_delta=1,
        now=now,
    )
    m = db.get_mastery("Q-TEST-01")
    assert m.leitner_box == 2
    assert m.total_attempts == 1
    assert m.total_correct == 1
    assert m.consecutive_correct == 1


def test_db_due_questions_returns_only_due(db):
    db.upsert_question(_sample_question(qid="Q-A", term="A"))
    db.upsert_question(_sample_question(qid="Q-B", term="B"))
    db.init_mastery("Q-A")
    db.init_mastery("Q-B")
    now = datetime.now(tz=JST)
    db.update_mastery(
        qid="Q-B",
        new_box=3,
        next_due=date(2099, 1, 1),
        consecutive_correct=0,
        total_attempts_delta=0,
        total_correct_delta=0,
        now=now,
    )
    due = db.due_questions(today=today_jst(), limit=10)
    ids = [q.id for q in due]
    assert "Q-A" in ids
    assert "Q-B" not in ids


def test_db_unseen_returns_unseen_only(db):
    db.upsert_question(_sample_question(qid="Q-A", stage=1))
    db.upsert_question(_sample_question(qid="Q-B", stage=1))
    db.init_mastery("Q-A")
    unseen = db.unseen_questions(stage=1, limit=10)
    assert [q.id for q in unseen] == ["Q-B"]


def test_db_mastery_summary_shape(db):
    db.upsert_question(_sample_question(qid="Q-A", stage=1))
    db.upsert_question(_sample_question(qid="Q-B", stage=2))
    db.init_mastery("Q-A")
    s = db.mastery_summary()
    assert s["total_questions"] == 2
    assert s["seen"] == 1
    assert s["mastered"] == 0
    assert 1 in s["box_distribution"]


# ========== Loader (YAML, ADR-005) ==========


def test_loader_parses_mcq_question(tmp_path: Path):
    f = tmp_path / "q_001.yml"
    f.write_text(
        "id: Q-001\n"
        "stage: 1\n"
        "category: basic\n"
        "term: テスト\n"
        "type: mcq\n"
        "difficulty: 1\n"
        "prereqs: []\n"
        "prompt: |\n"
        "  テスト質問です。\n"
        "rubric:\n"
        "  - keyword1\n"
        "  - keyword2\n"
        "choices:\n"
        '  A: "正解"\n'
        '  B: "不正解1"\n'
        '  C: "不正解2"\n'
        '  D: "不正解3"\n'
        "correct: A\n"
        "explanation: |\n"
        "  テスト解説内容。\n",
        encoding="utf-8",
    )
    q = parse_question_file(f)
    assert q.id == "Q-001"
    assert q.term == "テスト"
    assert q.question_type == "mcq"
    assert q.rubric == ["keyword1", "keyword2"]
    assert q.mcq_choices is not None
    assert len(q.mcq_choices) == 4
    assert q.correct_choice == "A"
    assert "テスト解説" in q.explanation


def test_loader_rejects_missing_keys(tmp_path: Path):
    f = tmp_path / "bad.yml"
    f.write_text(
        "id: Q-X\n"
        "stage: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing keys"):
        parse_question_file(f)


def test_loader_rejects_empty_prompt(tmp_path: Path):
    f = tmp_path / "bad2.yml"
    f.write_text(
        "id: Q-X\n"
        "stage: 1\n"
        "category: basic\n"
        "term: t\n"
        "type: mcq\n"
        "difficulty: 1\n"
        'prompt: ""\n'
        "choices:\n"
        '  A: "a"\n'
        '  B: "b"\n'
        "correct: A\n"
        "explanation: |\n"
        "  some text\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="prompt is empty"):
        parse_question_file(f)


def test_loader_rejects_mcq_without_choices(tmp_path: Path):
    f = tmp_path / "bad3.yml"
    f.write_text(
        "id: Q-X\n"
        "stage: 1\n"
        "category: basic\n"
        "term: t\n"
        "type: mcq\n"
        "difficulty: 1\n"
        "prompt: question\n"
        "correct: A\n"
        "explanation: explain\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mcq missing keys"):
        parse_question_file(f)


def test_loader_allows_mcq_without_rubric(tmp_path: Path):
    f = tmp_path / "mcq_no_rubric.yml"
    f.write_text(
        "id: Q-Y\n"
        "stage: 1\n"
        "category: basic\n"
        "term: t\n"
        "type: mcq\n"
        "difficulty: 1\n"
        "prompt: question\n"
        "choices:\n"
        '  A: "a"\n'
        '  B: "b"\n'
        "correct: A\n"
        "explanation: because a.\n",
        encoding="utf-8",
    )
    q = parse_question_file(f)
    assert q.rubric == []
    assert q.correct_choice == "A"


def test_loader_rejects_invalid_yaml(tmp_path: Path):
    f = tmp_path / "bad4.yml"
    f.write_text("not: [valid: yaml: {{", encoding="utf-8")
    with pytest.raises(Exception):
        parse_question_file(f)


def test_loader_handles_seed_questions():
    """Integration: load the actual seed questions shipped with the project."""
    seed_dir = Path("learning/data/questions/stage_1")
    if not seed_dir.exists():
        pytest.skip("seed questions not available")
    questions = load_all_questions(seed_dir)
    assert len(questions) >= 5
    assert all(q.stage == 1 for q in questions)
    assert all(q.prompt and q.explanation for q in questions)
    for q in questions:
        assert q.question_type == "mcq", f"{q.id}: expected mcq"
        assert q.correct_choice, f"{q.id}: mcq requires correct_choice"
        assert q.mcq_choices, f"{q.id}: mcq requires choices"
