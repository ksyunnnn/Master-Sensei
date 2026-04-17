"""Learning drill system (ADR-023).

Independent sub-app. Self-contained DB (learning/data/drill.duckdb)
and data (learning/data/questions/). Entry point: drill.py at repo root.
"""

from learning.db import LearningDB
from learning.scheduler import LeitnerScheduler

__all__ = ["LearningDB", "LeitnerScheduler"]
