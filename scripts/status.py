"""セッション開始時に人が見る「現在地」を1画面で出す (建玉 / 認証)。

`update_data.py` の末尾から呼ばれ、単独でも走る (`scripts/backup_db.py` と同じ形)。
冪等な read-only スクリプトなので何度実行してもよい。

**なぜスクリプトで、SessionStart フックではないか**: フックはセッション開始の
critical path に乗り、1回しか走らず、失敗しても再実行できない。依存を足すほど
起動が遅く・壊れやすくなる。スクリプトなら実行タイミングを選べ、失敗が見え、
同じ結果で何度でも走る。

出す2つはどちらも「知らないまま次の操作に進むと無駄が出る」もの:
  - 建玉: 含み損益を毎回手で計算し直さない。台帳 Parquet から出すので Saxo 認証が
    失効していても動く (`scripts/position_pnl.py` はライブ依存で失効中は動かない)。
  - 認証: 有効なら再認証を起動せずに済み、失効なら失敗する API 呼び出しを1回省ける。

使い方:
    python scripts/status.py              # 現値 (延長時間対応) で評価
    python scripts/status.py --no-realtime  # 終値で評価 (オフライン・高速)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb  # noqa: E402

from src.cache_manager import CacheManager  # noqa: E402
from src.db import SenseiDB, TokenStatus, now_jst  # noqa: E402
from src.position import LedgerPosition, format_valuation, value_position  # noqa: E402

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "sensei.duckdb"
PARQUET_DIR = ROOT / "data" / "parquet"
LEDGER_PATH = PARQUET_DIR / "account" / "transactions.parquet"

Emit = Callable[[str], None]


def humanize_elapsed(delta: timedelta) -> str:
    """経過時間を「2日3時間前」の形にする。失効からの経過を読ませるため。"""
    total = int(abs(delta).total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}日{hours}時間"
    if hours:
        return f"{hours}時間{minutes}分"
    return f"{minutes}分"


def format_token_status(st: TokenStatus, *, now: Optional[datetime] = None) -> str:
    """認証トークンの1行。失効時は再認証の入口まで書く。

    「失効」だけ出しても次の操作が決まらない。どのコマンドを叩けば直るかを
    同じ行に置く (会話を見ていない読者が単体で読める、GDR-004)。
    """
    now = now or now_jst()
    label = f"{st.token_type}:"
    if st.status == "missing":
        return f"  {label} 未取得 → python scripts/saxo_oauth_init.py で認証"
    stamp = st.expires_at.strftime("%Y-%m-%d %H:%M JST")
    if st.status == "valid":
        remaining = humanize_elapsed(st.expires_at - now)
        return f"  {label} 有効 (残り {remaining}, {stamp} まで / refresh {st.refresh_count}回)"
    elapsed = humanize_elapsed(now - st.expires_at)
    return (
        f"  {label} 失効 ({stamp} に期限切れ、{elapsed}前)"
        f" → python scripts/saxo_oauth_init.py で再認証"
    )


def _mark_from_realtime(symbol: str, cache: CacheManager) -> tuple[float, str, Optional[str]]:
    """延長時間対応の現値を (値, 出所ラベル, 注記) で返す (ADR-031)。"""
    from src.realtime import fetch_realtime_quote

    q = fetch_realtime_quote(symbol, cache=cache)
    note = "⚠薄商い(froth注意)" if q.is_thin else None
    return q.price, f"現値({q.session})", note


def _mark_from_close(symbol: str, cache: CacheManager) -> tuple[float, str, Optional[str]]:
    """Parquet の直近レギュラー終値。日付をラベルに入れて stale を隠さない。"""
    daily = cache.load_daily(symbol)
    if daily.empty:
        raise RuntimeError(f"{symbol}: 日足 Parquet が空")
    last = daily.iloc[-1]
    day = daily.index[-1]
    day = day.date() if hasattr(day, "date") else day
    return float(last["Close"]), f"{day.month}/{day.day:02d}終値", None


def _resolve_mark(
    symbol: str, cache: CacheManager, *, realtime: bool
) -> tuple[float, str, Optional[str]]:
    """評価に使う価格を決める。現値が取れなければ終値に落とす。

    現値の取得失敗で建玉の表示ごと消さない (含み損益は認証も回線も落ちている時ほど
    見たい)。落とした場合はラベルが終値の日付になるので、取り違えは起きない。
    """
    if realtime:
        try:
            return _mark_from_realtime(symbol, cache)
        except Exception:  # noqa: BLE001 — 現値が無くても終値で評価は続ける
            pass
    return _mark_from_close(symbol, cache)


def _emit_positions(
    db: SenseiDB, cache: CacheManager, emit: Emit, *, realtime: bool
) -> None:
    positions: dict[str, LedgerPosition] = db.get_ledger_positions(str(LEDGER_PATH))

    emit("[建玉 — 執行事実層(Saxo 台帳)から FIFO で導出・手数料込み]")
    if not positions:
        emit("  建玉なし")
        emit("")
        return

    for symbol in sorted(positions):
        try:
            mark, label, note = _resolve_mark(symbol, cache, realtime=realtime)
        except Exception as e:  # noqa: BLE001 — 1銘柄の価格欠損で全体を落とさない
            emit(f"  {symbol}: 価格を取得できず評価不能 ({e})")
            continue
        emit(format_valuation(value_position(positions[symbol], mark, label), note=note))

    # 判断層 trades と食い違っている時だけ鳴らす (一致が常態なので黙る)。
    for brk in db.reconcile_positions(str(LEDGER_PATH)):
        emit(
            f"  ⚠ {brk['instrument']}: 判断層 trades {brk['trades_open_qty']:g}株"
            f" ≠ 台帳 {brk['ledger_net_qty']:g}株 → /sync-saxo"
        )
    emit("")


def _emit_auth(db: SenseiDB, emit: Emit) -> None:
    emit("[Saxo 認証]")
    emit(format_token_status(db.get_token_status("saxo", "live", "refresh")))
    emit("")


def print_status(*, realtime: bool = True, emit: Emit = print) -> None:
    """建玉と認証の現在地を出力する。

    DB は read_only で開く。表示だけの処理が書き込みロックを取ると、同時に走る
    keepalive や oauth_init を待たせる (issue #34 と同じ形の詰まりを作らない)。
    """
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        db = SenseiDB(conn, init_schema=False)
        cache = CacheManager(PARQUET_DIR)
        _emit_positions(db, cache, emit, realtime=realtime)
        _emit_auth(db, emit)
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="建玉・認証の現在地を表示する")
    ap.add_argument(
        "--no-realtime", action="store_true",
        help="現値を取りに行かず直近終値で評価する (オフライン・高速)",
    )
    args = ap.parse_args()

    try:
        print_status(realtime=not args.no_realtime)
    except duckdb.IOException as e:
        print(f"DB を開けません (他プロセスが書き込みロック中の可能性): {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
