"""Saxo token keepalive (ADR-025 / ADR-026)。

目的: refresh token を**失効直前に1回だけ** roll して OAuth chain を生かす backstop。
これにより in-session の `SaxoClient` が必要時に access を on-demand 更新でき、
セッション中のブラウザ再認証(初動中断)を防ぐ。

設計方針(ユーザー確定仕様):
- **token 再発行は最低限**: access(公式20分)は温めない。refresh token(公式 doc 例 40分・
  当 LIVE アプリ実測 60分=app依存, `docs/api/saxo/token-auth.md`)の **expires_at を DB から読み**、
  失効直前(margin)に1回だけ roll する。数字はハードコードしない=Saxo 応答値に準拠(推測なし)。
- **起動契機**: /sync-saxo 実行時 or 明示指示のみ。セッション開始時の自動起動はしない
  (ログイン画面起動で初動が遅れるため)。
- **停止**: `run_in_background` のセッション子プロセスとして起動 → セッション終了でハーネスが kill。
  launchd / nohup-disown は使わない(永続化しない)。
- **リフレッサー1本厳守**: lockfile で二重起動を防止。

実行例(通常はバックグラウンド子プロセス):
  python scripts/saxo_keepalive.py
  python scripts/saxo_keepalive.py --once        # 1回チェックして終了(動作確認用)
"""
from __future__ import annotations

import argparse
import errno
import logging
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import duckdb

from src.db import SenseiDB, now_jst
from src.saxo_client import PROVIDER, SaxoAuthError, SaxoClient, SaxoConfig

logger = logging.getLogger("saxo_keepalive")

DB_PATH = PROJECT_ROOT / "data" / "sensei.duckdb"
LOG_PATH = PROJECT_ROOT / "logs" / "saxo_keepalive.log"
DEFAULT_LOCK_PATH = Path(tempfile.gettempdir()) / "master_sensei_saxo_keepalive.lock"

# refresh token の失効まで これ以下になったら roll する(秒)。poll は安価(DB読み)なので
# margin は小さく取り、再発行(API)は失効周期に1回=最小化する。
DEFAULT_MARGIN_SEC = 300
# 1回の sleep 上限(秒)。失効直前まで眠り過ぎず、外部 refresh / revoke を周期的に検知する。
DEFAULT_MAX_SLEEP_SEC = 300
# 一時障害(5xx/429/ネットワーク)時の再試行待ち(秒)。
DEFAULT_RETRY_SLEEP_SEC = 60


def plan_next(
    refresh_expires_at: datetime,
    now: datetime,
    margin_sec: float,
    max_sleep_sec: float,
) -> tuple[str, float]:
    """次アクションを決める純粋関数。

    refresh token の失効まで margin 以下なら ("refresh", 0)、
    まだ余裕があれば ("sleep", min(残り - margin, max_sleep))。
    """
    remaining = (refresh_expires_at - now).total_seconds()
    if remaining <= margin_sec:
        return ("refresh", 0.0)
    return ("sleep", min(remaining - margin_sec, float(max_sleep_sec)))


def run_keepalive(
    client: SaxoClient,
    db: SenseiDB,
    environment: str,
    *,
    margin_sec: float = DEFAULT_MARGIN_SEC,
    max_sleep_sec: float = DEFAULT_MAX_SLEEP_SEC,
    retry_sleep_sec: float = DEFAULT_RETRY_SLEEP_SEC,
    sleep_fn=time.sleep,
    stop_after: int | None = None,
) -> str:
    """keepalive ループ本体。終了理由文字列を返す。

    - "needs_reauth": refresh token 不在/失効 → ブラウザ再認証が必要(saxo_oauth_init)。
    - "refresh_no_progress": refresh 後も expiry が前進しない(access≥refresh の異常構成)。
    - "stopped": stop_after に到達(テスト用)。
    """
    iterations = 0
    while True:
        if stop_after is not None and iterations >= stop_after:
            return "stopped"

        row = db.get_active_token(PROVIDER, environment, "refresh")
        if row is None:
            logger.warning(
                "refresh token 不在/失効 → ブラウザ再認証が必要"
                "(python scripts/saxo_oauth_init.py)。keepalive 終了"
            )
            return "needs_reauth"

        action, sleep_for = plan_next(
            row["expires_at"], now_jst(), margin_sec, max_sleep_sec
        )

        if action == "refresh":
            before = row["expires_at"]
            try:
                # access は失効済(access<refresh)なので rolling refresh が走り、
                # 新 access + 新 refresh が発行される。
                client.get_access_token()
            except (SaxoAuthError, requests.RequestException) as exc:
                logger.warning(
                    "refresh 一時失敗(%s) → %ds 後に再試行", exc, retry_sleep_sec
                )
                sleep_fn(retry_sleep_sec)
                iterations += 1
                continue

            after = db.get_active_token(PROVIDER, environment, "refresh")
            if after is None:
                logger.warning("refresh 後に token 消失(revoked) → 要再認証。終了")
                return "needs_reauth"
            if after["expires_at"] <= before:
                logger.error(
                    "refresh 後も refresh expiry が未前進(access≥refresh 構成の疑い)。終了"
                )
                return "refresh_no_progress"
            logger.info(
                "token roll: refresh expiry %s → %s", before, after["expires_at"]
            )
            sleep_fn(1.0)
        else:
            sleep_fn(sleep_for)

        iterations += 1


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class SingleInstanceLock:
    """PID lockfile による二重起動防止(リフレッサー1本厳守)。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._held = False

    def acquire(self) -> bool:
        """取得できたら True。既に生存中の holder がいれば False。"""
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder = self._read_pid()
            if _pid_alive(holder):
                return False
            # stale lock(holder 死亡)→ 奪取を試みる
            try:
                self.path.unlink()
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except (FileExistsError, OSError):
                return False
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                return False
            raise
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        self._held = True
        return True

    def _read_pid(self) -> int:
        try:
            return int(self.path.read_text().strip() or "0")
        except (ValueError, OSError):
            return 0

    def release(self) -> None:
        if self._held:
            try:
                self.path.unlink()
            except OSError:
                pass
            self._held = False


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stderr)]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Saxo token keepalive (ADR-025/026)")
    parser.add_argument("--env", choices=["sim", "live"], default=None)
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN_SEC)
    parser.add_argument("--max-sleep", type=float, default=DEFAULT_MAX_SLEEP_SEC)
    parser.add_argument("--lock", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument("--once", action="store_true",
                        help="1回チェックして終了(動作確認用)")
    args = parser.parse_args()

    _setup_logging()

    lock = SingleInstanceLock(args.lock)
    if not lock.acquire():
        logger.info("keepalive は既に起動中(lock=%s)。リフレッサー1本厳守で終了", args.lock)
        return 0

    try:
        config = SaxoConfig.from_env(environment=args.env)
        conn = duckdb.connect(str(DB_PATH))
        try:
            db = SenseiDB(conn)
            client = SaxoClient(db, config=config)
            logger.info("keepalive 開始(env=%s, margin=%.0fs)", config.environment, args.margin)
            status = run_keepalive(
                client, db, config.environment,
                margin_sec=args.margin, max_sleep_sec=args.max_sleep,
                stop_after=1 if args.once else None,
            )
        finally:
            conn.close()
    finally:
        lock.release()

    logger.info("keepalive 終了: %s", status)
    return {"needs_reauth": 2, "refresh_no_progress": 3}.get(status, 0)


if __name__ == "__main__":
    sys.exit(main())
