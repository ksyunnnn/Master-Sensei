# Changelog

All notable changes to the learning drill app will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: CalVer-ish (`vYYYY.MM.patch` once released).

## [Unreleased]

## [0.2.0] - 2026-04-17

Grading overhaul: full MCQ with objective scoring (ADR-005, supersedes ADR-003).

### Added
- `grading_method` column in `learning_attempts` ('self' | 'mcq_auto' | 'llm')
- Distractor design standard: each question requires at least 1 misconception-based distractor
- Re-evaluation triggers for Stage 3-4 recall + LLM grading consideration
- YAML schema validation in loader
- New tests: grading_method recording, MCQ auto-grading, invalid grading_method rejection

### Changed
- **All 10 questions converted to MCQ** (objective 4-choice format)
- **Question files: Markdown (.md) -> pure YAML (.yml)** — all fields in YAML, no markdown sections
- `loader.py`: rewritten from markdown section parser to `yaml.safe_load()` based
- `cli.py`: removed self-rating flow, all questions use MCQ auto-grading
- `db.py`: `self_rating` now nullable, `record_attempt()` accepts `grading_method` parameter
- `record_attempt()` signature: `self_rating` moved to keyword-only, `outcome` is now positional after `user_answer`

### Removed
- `_ask_recall()` function (all questions are MCQ)
- `_prompt_self_rating()` function
- `_rating_to_outcome()` function
- Markdown question files (.md) replaced by YAML (.yml)

## [0.1.0] - 2026-04-17

First user-tested MVP. Independent from the parent Master Sensei app (own DB,
own package tree, own docs).

### Added
- Leitner 5-box scheduler (`learning/scheduler.py`)
- DuckDB CRUD for `learning_questions` / `learning_attempts` / `learning_mastery`
  in `learning/data/drill.duckdb` (`learning/db.py`)
- Markdown question loader with YAML front matter (`learning/loader.py`)
- Interactive CLI with `drill.py` entry point: `--stats`, `--reload`, `-n N`
- Free recall + self-rating (A/B/C) with rubric reveal post-answer
- MCQ variant with immediate correctness feedback
- Stage 1 seed: 10 questions covering 株式, 指数, ETF, リターン, ボラティリティ,
  σ (SD), SMA20, 債券, 先物, 3x レバレッジ
- `/learn-status` Skill for Claude-side curriculum review
- 22 unit tests (scheduler / db / loader)
- `docs/curriculum.md` — Stage 1-4 design + 2026-04-16 diagnosis (A=2/B=5/C=11)

### Changed
- Separated from parent app: code moved `src/learning/` → `learning/`,
  questions moved `data/learning/questions/` → `learning/data/questions/`,
  tests moved `tests/test_learning.py` → `learning/tests/test_learning.py`

### Removed
- `src/learning/` package (moved)
- `learning_*` tables from `sensei.duckdb` (dropped, replaced by
  `learning/data/drill.duckdb`)

### Notes
- Parent-project ADR-023 remains as a pointer to this app's internal ADR set
- Known item: user reported anxiety around self-grading of free recall; design
  alternatives (full MCQ / AI-graded free text / hybrid) deferred to v0.2
- Known item: Japanese free input feels clunky (post-answer operation keys);
  UX improvement deferred to v0.2
