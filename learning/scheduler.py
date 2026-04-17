"""Leitner 5-box scheduler (ADR-023).

Intervals (days): Box 1 -> 1d, Box 2 -> 2d, Box 3 -> 4d, Box 4 -> 8d, Box 5 -> 16d.
- outcome='correct' -> box + 1 (cap 5)
- outcome='partial' -> same box, next_due = today + current interval
- outcome='wrong'   -> box = 1
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


BOX_INTERVALS = {1: 1, 2: 2, 3: 4, 4: 8, 5: 16}


@dataclass
class ScheduleDecision:
    new_box: int
    next_due_date: date
    consecutive_correct: int


class LeitnerScheduler:
    """Pure function container; holds no state."""

    @staticmethod
    def schedule_next(
        current_box: int,
        outcome: str,
        current_consecutive_correct: int,
        today: date,
    ) -> ScheduleDecision:
        if outcome not in {"correct", "partial", "wrong"}:
            raise ValueError(f"outcome invalid: {outcome}")
        if current_box < 1 or current_box > 5:
            raise ValueError(f"box out of range 1-5: {current_box}")

        if outcome == "correct":
            new_box = min(current_box + 1, 5)
            consecutive = current_consecutive_correct + 1
        elif outcome == "partial":
            new_box = current_box
            consecutive = 0
        else:  # wrong
            new_box = 1
            consecutive = 0

        interval = BOX_INTERVALS[new_box]
        next_due = today + timedelta(days=interval)
        return ScheduleDecision(
            new_box=new_box,
            next_due_date=next_due,
            consecutive_correct=consecutive,
        )

    @staticmethod
    def is_mastered(box: int, consecutive_correct: int) -> bool:
        """Box 5 reached with at least 2 consecutive correct = mastered."""
        return box == 5 and consecutive_correct >= 2
