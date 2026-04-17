"""YAML question loader (ADR-005).

Parses pure YAML question files (.yml).

Expected format:

    id: Q-001
    stage: 1
    category: basic
    term: ETF
    type: mcq
    difficulty: 1
    prereqs: []
    prompt: |
      Question text here.
    rubric:
      - keyword1
      - keyword2
    choices:
      A: "choice text"
      B: "choice text"
      C: "choice text"
      D: "choice text"
    correct: A
    explanation: |
      Explanation text here.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from learning.db import Question

_REQUIRED_KEYS = {"id", "stage", "category", "term", "type", "difficulty", "prompt", "explanation"}
_MCQ_REQUIRED_KEYS = {"choices", "correct"}


def parse_question_file(path: Path) -> Question:
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    if not isinstance(data, dict):
        raise ValueError(f"{path}: invalid YAML (expected mapping)")

    missing = _REQUIRED_KEYS - data.keys()
    if missing:
        raise ValueError(f"{path}: missing keys: {missing}")

    prompt = str(data["prompt"]).strip()
    explanation = str(data["explanation"]).strip()

    if not prompt:
        raise ValueError(f"{path}: prompt is empty")
    if not explanation:
        raise ValueError(f"{path}: explanation is empty")

    qtype = data["type"]

    rubric = data.get("rubric") or []
    if not isinstance(rubric, list):
        raise ValueError(f"{path}: rubric must be a list")

    if qtype != "mcq" and not rubric:
        raise ValueError(f"{path}: non-mcq requires rubric")

    mcq_choices = None
    correct_choice = None
    if qtype == "mcq":
        mcq_missing = _MCQ_REQUIRED_KEYS - data.keys()
        if mcq_missing:
            raise ValueError(f"{path}: mcq missing keys: {mcq_missing}")

        choices_raw = data["choices"]
        if not isinstance(choices_raw, dict) or not choices_raw:
            raise ValueError(f"{path}: choices must be a non-empty mapping")

        mcq_choices = [f"{k}. {v}" for k, v in choices_raw.items()]
        correct_choice = str(data["correct"]).strip().upper()

    prereqs = data.get("prereqs") or None
    if isinstance(prereqs, list) and not prereqs:
        prereqs = None

    return Question(
        id=data["id"],
        stage=int(data["stage"]),
        category=data["category"],
        term=data["term"],
        question_type=qtype,
        prompt=prompt,
        rubric=rubric,
        explanation=explanation,
        mcq_choices=mcq_choices,
        correct_choice=correct_choice,
        prereqs=prereqs,
        difficulty=int(data["difficulty"]),
        source_file=str(path),
    )


def load_all_questions(questions_dir: Path) -> list[Question]:
    """Recursively load all .yml files under questions_dir."""
    files = sorted(questions_dir.rglob("*.yml"))
    return [parse_question_file(p) for p in files]
