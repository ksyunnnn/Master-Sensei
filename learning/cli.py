"""Interactive CLI for learning drill (ADR-023)."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb

from learning.db import LearningDB, Question
from learning.loader import load_all_questions
from learning.scheduler import BOX_INTERVALS, LeitnerScheduler
from learning.timeutil import now_jst, today_jst

DB_PATH = Path("learning/data/drill.duckdb")
QUESTIONS_DIR = Path("learning/data/questions")


# ---------- Formatting helpers ----------


def _line(char: str = "─", width: int = 60) -> str:
    return char * width


def _header(title: str) -> str:
    return f"\n{_line('=')}\n {title}\n{_line('=')}"


# ---------- Core workflow ----------


def _ask_recall(q: Question) -> tuple[str, str]:
    """Return (user_answer, self_rating)."""
    print(_header(f"[{q.id}] Term: {q.term}  (Stage {q.stage}, difficulty {q.difficulty})"))
    print(f"\n{q.prompt}\n")
    print("入力完了したら空行で Enter を押してください。(q で中断)")
    print(_line())
    lines: list[str] = []
    while True:
        try:
            line = input("> ")
        except EOFError:
            break
        if line.strip().lower() == "q":
            raise KeyboardInterrupt
        if line == "" and lines:
            break
        if line == "" and not lines:
            continue
        lines.append(line)
    user_answer = "\n".join(lines).strip()

    print(f"\n{_line()}\n【模範解答のキーワード (Rubric)】")
    for item in q.rubric:
        print(f"  - {item}")
    print(f"\n【解説】\n{q.explanation}\n{_line()}")

    rating = _prompt_self_rating()
    return user_answer, rating


def _ask_mcq(q: Question) -> tuple[str, str]:
    """Return (user_choice, self_rating)."""
    print(_header(f"[{q.id}] Term: {q.term}  (Stage {q.stage}, difficulty {q.difficulty})"))
    print(f"\n{q.prompt}\n")
    for choice in q.mcq_choices or []:
        print(f"  {choice}")
    print(f"\n{_line()}")
    while True:
        ans = input("選択肢のアルファベットを入力 (q で中断): ").strip().upper()
        if ans == "Q":
            raise KeyboardInterrupt
        if ans and ans[0].isalpha():
            user_choice = ans[0]
            break
        print("A, B, C... のどれかを入力してください")

    correct = (q.correct_choice or "").strip().upper()
    is_correct = user_choice == correct
    verdict = "✓ 正解" if is_correct else f"✗ 不正解 (正解: {correct})"
    print(f"\n{verdict}\n\n【解説】\n{q.explanation}\n{_line()}")

    # Pre-fill outcome based on MCQ correctness, user still rates own confidence
    rating = _prompt_self_rating(default_hint=("A" if is_correct else "C"))
    return user_choice, rating


def _prompt_self_rating(default_hint: str | None = None) -> str:
    hint = f" (ヒント: {default_hint})" if default_hint else ""
    while True:
        print("\n自己評価してください:")
        print("  A = 完全に理解 / 正解")
        print("  B = 部分的 / 曖昧")
        print("  C = 分からなかった / 誤り")
        ans = input(f"> A / B / C{hint}: ").strip().upper()
        if ans in {"A", "B", "C"}:
            return ans


def _rating_to_outcome(rating: str) -> str:
    return {"A": "correct", "B": "partial", "C": "wrong"}[rating]


def _apply_result(
    db: LearningDB,
    q: Question,
    user_answer: str,
    rating: str,
    time_spent: int,
) -> None:
    outcome = _rating_to_outcome(rating)
    today = today_jst()
    now = now_jst()

    # Ensure mastery row exists
    m = db.get_mastery(q.id) or db.init_mastery(q.id)

    decision = LeitnerScheduler.schedule_next(
        current_box=m.leitner_box,
        outcome=outcome,
        current_consecutive_correct=m.consecutive_correct,
        today=today,
    )

    db.record_attempt(
        question_id=q.id,
        user_answer=user_answer or None,
        self_rating=rating,
        outcome=outcome,
        time_spent_seconds=time_spent,
        attempted_at=now,
    )
    db.update_mastery(
        qid=q.id,
        new_box=decision.new_box,
        next_due=decision.next_due_date,
        consecutive_correct=decision.consecutive_correct,
        total_attempts_delta=1,
        total_correct_delta=(1 if outcome == "correct" else 0),
        now=now,
    )

    interval_days = BOX_INTERVALS[decision.new_box]
    print(
        f"\n→ Box {m.leitner_box} → Box {decision.new_box}、"
        f"次回出題予定 {decision.next_due_date} (+{interval_days}d)"
    )
    if LeitnerScheduler.is_mastered(decision.new_box, decision.consecutive_correct):
        print(f"🎓 '{q.term}' が mastered に到達しました！")


# ---------- Commands ----------


def cmd_practice(db: LearningDB, max_count: int, stage_hint: int | None) -> None:
    today = today_jst()
    due = db.due_questions(today=today, limit=max_count)
    target_stage = stage_hint or 1
    unseen_count = max(0, max_count - len(due))
    unseen = db.unseen_questions(stage=target_stage, limit=unseen_count)
    queue: list[Question] = due + unseen

    if not queue:
        print("今日のノルマは終了しています。お疲れさまでした。")
        print("新規質問を追加するか、`python drill.py --stats` で進捗を確認してください。")
        return

    print(_header(f"Drill Session — {len(queue)} 問 (due {len(due)} + new {len(unseen)})"))
    for idx, q in enumerate(queue, start=1):
        print(f"\n## {idx}/{len(queue)}")
        started = time.monotonic()
        try:
            if q.question_type == "mcq":
                user_answer, rating = _ask_mcq(q)
            else:
                user_answer, rating = _ask_recall(q)
        except KeyboardInterrupt:
            print("\n中断しました。ここまでの結果は保存済みです。")
            return
        elapsed = int(time.monotonic() - started)
        _apply_result(db, q, user_answer, rating, elapsed)

    print(_header("セッション完了"))
    cmd_stats(db)


def cmd_stats(db: LearningDB) -> None:
    s = db.mastery_summary()
    print(_header("進捗サマリ"))
    print(f"  全質問数: {s['total_questions']}")
    print(f"  学習済み: {s['seen']} ({_pct(s['seen'], s['total_questions'])})")
    print(f"  Mastered (Box 5): {s['mastered']}")
    print("\n  Box 分布:")
    for box in range(1, 6):
        count = s["box_distribution"].get(box, 0)
        bar = "█" * count
        print(f"    Box {box} (int {BOX_INTERVALS[box]}d): {count:3d}  {bar}")

    if s["stage_breakdown"]:
        print("\n  Stage 進捗 (seen / total):")
        stage_totals = {
            row[0]: row[1]
            for row in db.conn.execute(
                "SELECT stage, COUNT(*) FROM learning_questions GROUP BY stage"
            ).fetchall()
        }
        for stage, seen in s["stage_breakdown"]:
            total = stage_totals.get(stage, 0)
            print(f"    Stage {stage}: {seen} / {total}  ({_pct(seen, total)})")

    weak = db.weak_terms(min_attempts=2)
    if weak:
        print("\n  苦手トピック (attempt≥2):")
        for term, attempts, wrongs, score in weak[:5]:
            print(f"    - {term}: score {score} / {attempts}回 (誤答 {wrongs})")


def cmd_reload(db: LearningDB) -> None:
    if not QUESTIONS_DIR.exists():
        print(f"{QUESTIONS_DIR} がありません。まず質問ファイルを配置してください。")
        return
    questions = load_all_questions(QUESTIONS_DIR)
    for q in questions:
        db.upsert_question(q)
    print(f"Loaded {len(questions)} questions from {QUESTIONS_DIR}")


def _pct(n: int, total: int) -> str:
    if total == 0:
        return "0%"
    return f"{n * 100 // total}%"


# ---------- Entry ----------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Master Sensei 学習ドリル (ADR-023)",
    )
    p.add_argument("--stats", action="store_true", help="進捗サマリのみ表示")
    p.add_argument("--reload", action="store_true", help="質問 Markdown を DB に再ロード")
    p.add_argument(
        "-n",
        "--count",
        type=int,
        default=5,
        help="1 セッションの最大問題数 (デフォルト 5)",
    )
    p.add_argument(
        "--stage",
        type=int,
        default=None,
        help="新規質問のステージヒント (デフォルト 1)",
    )
    return p


def run(argv: list[str] | None = None) -> None:
    args = build_argparser().parse_args(argv)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH))
    db = LearningDB(conn)

    # Auto-reload on every start so markdown edits propagate
    if QUESTIONS_DIR.exists():
        cmd_reload(db)

    try:
        if args.stats:
            cmd_stats(db)
        elif args.reload:
            # already reloaded above; still report
            pass
        else:
            cmd_practice(db, max_count=args.count, stage_hint=args.stage)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
