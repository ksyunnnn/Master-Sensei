"""Entry point for the learning drill CLI (ADR-023).

Usage:
    python drill.py                 # Start a drill session (default 5 questions)
    python drill.py --stats         # Show progress summary
    python drill.py --reload        # Reload questions from Markdown into DB
    python drill.py -n 10           # 10-question session
    python drill.py --stage 2       # Pull new items from Stage 2 if due queue is empty
"""

from learning.cli import run

if __name__ == "__main__":
    run()
