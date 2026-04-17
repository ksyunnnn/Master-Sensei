# Changelog

All notable changes to the learning drill app will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: CalVer-ish (`vYYYY.MM.patch` once released).

## [Unreleased]

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
