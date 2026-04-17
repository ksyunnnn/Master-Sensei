"""Markdown question loader (ADR-023).

Parses a Markdown file with YAML front matter + canonical sections.

Expected format:

    ---
    id: Q-001
    stage: 1
    category: basic
    term: ETF
    type: recall | mcq | application
    difficulty: 1
    prereqs: []
    ---

    ## Prompt
    ...

    ## Rubric
    - item1
    - item2

    ## Choices          (only for type=mcq)
    A. ...
    B. ...

    ## Correct          (only for type=mcq)
    A

    ## Explanation
    ...
"""

from __future__ import annotations

import re
from pathlib import Path

from learning.db import Question

_FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _parse_yaml_simple(text: str) -> dict:
    """Minimal YAML parser for flat key: value + lists like prereqs: [a, b]."""
    out: dict = {}
    for line in text.strip().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items = [s.strip() for s in inner.split(",") if s.strip()] if inner else []
            out[key] = items
        elif value.isdigit():
            out[key] = int(value)
        else:
            out[key] = value.strip('"').strip("'")
    return out


def _split_sections(body: str) -> dict[str, str]:
    """Split body by `## Section` headings. Returns lowercase-keyed dict."""
    sections: dict[str, str] = {}
    positions = [(m.start(), m.end(), m.group(1).strip()) for m in _SECTION_RE.finditer(body)]
    if not positions:
        return sections
    for i, (_, end, name) in enumerate(positions):
        next_start = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        content = body[end:next_start].strip()
        sections[name.lower()] = content
    return sections


def _parse_list_block(text: str) -> list[str]:
    """Extract `- item` lines into a list of strings."""
    items = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("-"):
            items.append(s.lstrip("-").strip())
    return items


def _parse_mcq_choices(text: str) -> list[str]:
    """Parse `A. foo\nB. bar` style choices into list preserving order."""
    items = []
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"^[A-Z][\.\)]\s+", s):
            items.append(s)
    return items


def parse_question_file(path: Path) -> Question:
    raw = path.read_text(encoding="utf-8")
    m = _FRONT_MATTER_RE.match(raw)
    if not m:
        raise ValueError(f"no front matter in {path}")
    fm_text, body = m.group(1), m.group(2)
    fm = _parse_yaml_simple(fm_text)

    required = {"id", "stage", "category", "term", "type", "difficulty"}
    missing = required - fm.keys()
    if missing:
        raise ValueError(f"{path}: missing front matter keys: {missing}")

    sections = _split_sections(body)
    prompt = sections.get("prompt", "").strip()
    rubric = _parse_list_block(sections.get("rubric", ""))
    explanation = sections.get("explanation", "").strip()

    if not prompt:
        raise ValueError(f"{path}: Prompt section empty")
    if not explanation:
        raise ValueError(f"{path}: Explanation section empty")

    qtype = fm["type"]
    if qtype != "mcq" and not rubric:
        # Rubric required for free recall; MCQ derives truth from Correct section
        raise ValueError(f"{path}: Rubric section empty")
    mcq_choices = None
    correct_choice = None
    if qtype == "mcq":
        mcq_choices = _parse_mcq_choices(sections.get("choices", ""))
        correct_choice = sections.get("correct", "").strip()
        if not mcq_choices:
            raise ValueError(f"{path}: mcq missing Choices section")
        if not correct_choice:
            raise ValueError(f"{path}: mcq missing Correct section")

    return Question(
        id=fm["id"],
        stage=int(fm["stage"]),
        category=fm["category"],
        term=fm["term"],
        question_type=qtype,
        prompt=prompt,
        rubric=rubric,
        explanation=explanation,
        mcq_choices=mcq_choices,
        correct_choice=correct_choice,
        prereqs=fm.get("prereqs") or None,
        difficulty=int(fm["difficulty"]),
        source_file=str(path),
    )


def load_all_questions(questions_dir: Path) -> list[Question]:
    """Recursively load all .md files under questions_dir."""
    files = sorted(questions_dir.rglob("*.md"))
    return [parse_question_file(p) for p in files]
