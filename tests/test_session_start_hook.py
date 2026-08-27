"""SessionStart hook の状態注入テスト。

`get_stale_knowledge()` は `last_verified_date IS NULL` の行と
`last_verified_date < current_date - 180 days` の行を同じリストで返す
(`src/db.py`)。フックがこの2種類を区別せず「180日以上未検証」と
まとめて表示すると、作成直後の知見まで「180日以上」と数えてしまい、
警告の件数そのものが事実と異なる状態になる。
"""
import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
HOOK_PATH = PROJECT_ROOT / ".claude" / "hooks" / "session_start.py"


def _load_hook():
    """`.claude/hooks/session_start.py` をモジュールとして読み込む。

    パッケージ配下にないファイルなので通常の import では届かない。
    """
    spec = importlib.util.spec_from_file_location("session_start_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["session_start_hook"] = module
    spec.loader.exec_module(module)
    return module


class FakeDB:
    """`check_knowledge` が呼ぶ2メソッドだけを持つ最小のスタブ。"""

    def __init__(self, active, stale):
        self._active = active
        self._stale = stale

    def get_active_knowledge(self):
        return self._active

    def get_stale_knowledge(self):
        return self._stale


def _row(knowledge_id, last_verified_date, created_at):
    return {
        "id": knowledge_id,
        "last_verified_date": last_verified_date,
        "created_at": created_at,
    }


@pytest.fixture
def hook():
    return _load_hook()


def test_未検証と180日超を別々に数える(hook):
    """NULL の行を「180日以上未検証」に混ぜない。

    2026-08-27 時点の実データがまさにこの形で、
    26件すべてが NULL・180日超は0件なのに「26件が180日以上未検証」と
    表示されていた。
    """
    today = date(2026, 8, 27)
    stale = [
        _row("K-076", None, today - timedelta(days=2)),
        _row("K-041", None, today - timedelta(days=86)),
        _row("K-001", today - timedelta(days=200), today - timedelta(days=400)),
    ]
    messages = hook.check_knowledge(FakeDB(active=[1, 2, 3], stale=stale))
    joined = "\n".join(messages)

    assert "3件が180日以上未検証" not in joined, (
        "NULL の2件を180日超に数え込んではいけない"
    )
    assert "1件が180日以上未検証" in joined
    assert "2件" in joined and "検証日なし" in joined


def test_180日超が無ければ警告を出さない(hook):
    """NULL しか無い時に [警告] を立てない。

    作成直後の知見が未検証なのは正常な状態であり、
    毎セッション点灯する警告は情報を持たない。
    """
    today = date(2026, 8, 27)
    stale = [
        _row("K-076", None, today - timedelta(days=2)),
        _row("K-075", None, today - timedelta(days=5)),
    ]
    messages = hook.check_knowledge(FakeDB(active=[1, 2], stale=stale))
    joined = "\n".join(messages)

    assert "[警告]" not in joined
    assert "検証日なし" in joined
    assert "2件" in joined


def test_staleが空なら件数行だけ返す(hook):
    messages = hook.check_knowledge(FakeDB(active=[1, 2, 3], stale=[]))

    assert len(messages) == 1
    assert "知見: 3件 (active)" in messages[0]


def test_active件数は常に出る(hook):
    today = date(2026, 8, 27)
    stale = [_row("K-001", today - timedelta(days=300), today - timedelta(days=400))]
    messages = hook.check_knowledge(FakeDB(active=[1] * 74, stale=stale))

    assert "知見: 74件 (active)" in messages[0]


def test_pandasのNaTを未検証として数える(hook):
    """`SenseiDB` は `fetchdf().to_dict("records")` で行を返すため、
    SQL の NULL は `None` ではなく `NaT` で届く。

    `is None` だけで判定していた実装は、実データ26件すべてを
    「180日以上未検証」に数え込んでいた（2026-08-27 に実測）。
    """
    import pandas as pd

    today = date(2026, 8, 27)
    stale = [
        _row("K-076", pd.NaT, today - timedelta(days=2)),
        _row("K-041", pd.NaT, today - timedelta(days=86)),
    ]
    messages = hook.check_knowledge(FakeDB(active=[1, 2], stale=stale))
    joined = "\n".join(messages)

    assert "[警告]" not in joined
    assert "検証日なし): 2件" in joined
