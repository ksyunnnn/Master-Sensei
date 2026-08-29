"""Saxo OpenAPI 初回認可 CLI (ADR-025)

Authorization Code grant の初回フローを対話的に実行する:
  1. localhost:8080 で一時 HTTP サーバ起動
  2. Saxo 認可URLをブラウザで開く
  3. ユーザが Saxo にログイン → callback で code 受領
  4. code を access+refresh token に交換 → DuckDB に保存
  5. サーバ停止

実行: python scripts/saxo_oauth_init.py
再実行が必要なタイミング: refresh token 期限切れ (60〜90日に1回)
"""
from __future__ import annotations

import argparse
import ipaddress
import logging
import secrets
import stat
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db import SenseiDB
from src.saxo_client import SaxoAuthError, SaxoClient, SaxoConfig

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "sensei.duckdb"

# ADR-025: token_value plaintext を含む DB ファイルは owner-only にする
DB_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0o600


class _CallbackResult:
    """callback で受け取った code / state / error を保持する worker shared state"""

    def __init__(self):
        self.code: str | None = None
        self.state: str | None = None
        self.error: str | None = None
        self.event = threading.Event()


def _make_handler(expected_state: str, result: _CallbackResult):
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/callback"):
                self.send_response(404)
                self.end_headers()
                return

            # idempotency: 既に callback 処理済みなら何もしない (race 防止)
            if result.event.is_set():
                self.send_response(200)
                self.end_headers()
                return

            params = parse_qs(parsed.query)
            received_state = (params.get("state") or [None])[0]
            received_code = (params.get("code") or [None])[0]
            received_error = (params.get("error") or [None])[0]

            if received_error:
                result.error = received_error
            elif received_state != expected_state:
                # SECURITY: expected_state は session secret なので error message に含めない
                result.error = (
                    f"state mismatch: callback returned unexpected state (got={received_state!r})"
                )
            elif not received_code:
                result.error = "no code in callback"
            else:
                result.code = received_code
                result.state = received_state

            body = (
                b"<html><body><h2>Saxo OAuth callback received</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            result.event.set()

        def log_message(self, format, *args):
            # quiet down stdlib HTTPServer's stderr logging
            pass

    return CallbackHandler


def _validate_loopback_host(host: str | None) -> None:
    """redirect_uri の host が loopback 専用であることを保証 (network exposure 防止)"""
    if host is None:
        raise SystemExit(
            "SAXO_REDIRECT_URI hostname could not be parsed. "
            "Ensure URI starts with http:// and includes host (e.g., http://localhost:8080/callback)"
        )
    if host == "localhost":
        return
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        raise SystemExit(
            f"SAXO_REDIRECT_URI host must be 'localhost' or a loopback IP, got {host!r}"
        )
    if not addr.is_loopback:
        raise SystemExit(
            f"SAXO_REDIRECT_URI host must be a loopback address (127.0.0.1 or ::1), got {host!r}. "
            "Binding to non-loopback exposes the OAuth callback to the network."
        )


def _ensure_db_file_mode(path: Path) -> None:
    """DB ファイルが存在すれば 0o600 に強制 (ADR-025)"""
    if path.exists():
        try:
            path.chmod(DB_FILE_MODE)
        except OSError as exc:
            logger.warning("Could not chmod %s to 0o600: %s", path, exc)


def run_oauth_init(environment: str | None = None, port: int = 8080,
                   open_browser: bool = True, wait_sec: int = 300) -> None:
    config = SaxoConfig.from_env(environment=environment)
    parsed_redirect = urlparse(config.redirect_uri)
    expected_host = parsed_redirect.hostname
    expected_port = parsed_redirect.port

    _validate_loopback_host(expected_host)
    if expected_port != port:
        raise SystemExit(
            f"Port mismatch: SAXO_REDIRECT_URI port={expected_port} but CLI port={port}. "
            f"Set --port {expected_port} or update SAXO_REDIRECT_URI in .env"
        )

    conn = duckdb.connect(str(DB_PATH))
    _ensure_db_file_mode(DB_PATH)
    db = SenseiDB(conn)
    try:
        client = SaxoClient(db, config=config)

        state = secrets.token_urlsafe(24)
        auth_url = client.build_authorization_url(state=state)

        result = _CallbackResult()
        server = HTTPServer((expected_host, port), _make_handler(state, result))
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            print(f"[saxo-oauth-init] environment: {config.environment}")
            print(f"[saxo-oauth-init] listening on http://{expected_host}:{port}/callback")
            print(f"[saxo-oauth-init] Open this URL in your browser if it does not open automatically:")
            print(f"\n  {auth_url}\n")
            if open_browser:
                webbrowser.open(auth_url)

            # 手動ログインが終わるまで block。callback は localhost に返るため、
            # ログインはこの PC のブラウザでしか完了できない。ユーザーが席を外して
            # いる間に token が失効した場合は、戻るまで窓を開けておく必要がある
            # (--wait-min で延ばす)。
            if not result.event.wait(timeout=wait_sec):
                raise SystemExit(
                    f"[saxo-oauth-init] timeout waiting for callback "
                    f"({wait_sec // 60} min {wait_sec % 60} sec)"
                )

            if result.error:
                raise SystemExit(f"[saxo-oauth-init] callback error: {result.error}")

            print("[saxo-oauth-init] code received, exchanging for tokens...")
            client.exchange_code_for_tokens(code=result.code)
            print(f"[saxo-oauth-init] OK. access + refresh tokens saved to {DB_PATH}")
        finally:
            server.shutdown()
            server.server_close()
    finally:
        conn.close()
        _ensure_db_file_mode(DB_PATH)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Saxo OpenAPI 初回認可 CLI")
    parser.add_argument("--env", choices=["sim", "live"], default=None,
                        help="環境 (.env の SAXO_ENVIRONMENT を上書き)")
    parser.add_argument("--port", type=int, default=8080,
                        help="callback リスナーのポート (default: 8080)")
    parser.add_argument("--no-browser", action="store_true",
                        help="ブラウザを自動で開かない")
    parser.add_argument("--wait-min", type=float, default=5.0,
                        help="callback を待つ分数 (default: 5)。席を外している間に "
                             "token が失効した時は長く取る。callback は localhost に "
                             "返るのでログインはこの PC のブラウザでしか完了できない")
    args = parser.parse_args()

    try:
        run_oauth_init(environment=args.env, port=args.port,
                       open_browser=not args.no_browser,
                       wait_sec=int(args.wait_min * 60))
    except (SaxoAuthError, ValueError) as e:
        print(f"[saxo-oauth-init] ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
