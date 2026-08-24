"""update_data の並列 fetch ヘルパーのテスト。

Tiingo は公式に「秒・分単位の制限なし／同時実行制限なし」(docs/api/tiingo/rate-limits.md)
なので fetch を並列化する。本テストは並列化が (1) 結果を items 順に整列し
(2) 1銘柄の失敗で全体を止めず (3) 全件を fetch することを保証する。
"""
from __future__ import annotations

import threading

import update_data


def test_parallel_fetch_preserves_order():
    items = [1, 2, 3, 4, 5]
    out = update_data._parallel_fetch(items, lambda x: x * 10, max_workers=4)
    assert out == [(1, 10), (2, 20), (3, 30), (4, 40), (5, 50)]


def test_parallel_fetch_isolates_failures():
    """1件が例外を投げても他は成功し、失敗は (item, None) になる。"""
    def fetch(x):
        if x == 3:
            raise RuntimeError("boom")
        return x * 10
    out = update_data._parallel_fetch([1, 2, 3, 4], fetch, max_workers=4)
    assert out == [(1, 10), (2, 20), (3, None), (4, 40)]


def test_parallel_fetch_runs_all():
    items = list(range(20))
    out = update_data._parallel_fetch(items, lambda x: x, max_workers=8)
    assert [r for _, r in out] == items


def test_parallel_fetch_empty():
    assert update_data._parallel_fetch([], lambda x: x, max_workers=4) == []


def test_parallel_fetch_actually_concurrent():
    """max_workers>1 で実際に並走する (逐次なら所要≈N×sleep、並列なら≈sleep)。"""
    barrier = threading.Barrier(4, timeout=5)

    def fetch(x):
        barrier.wait()  # 4スレッドが揃わないと進めない → 逐次では deadlock/timeout
        return x

    out = update_data._parallel_fetch([1, 2, 3, 4], fetch, max_workers=4)
    assert sorted(r for _, r in out) == [1, 2, 3, 4]


class TestUnusualMoveFlag:
    """マクロ系列の「いつもと違う動き」の検出 (K-075 の段4: 異常検知)。

    金利分解系列は翌日を予測しないため判定には使えないが、大きく動いた日は
    「見に行くべき日」の合図になる。誰も見ていないと収集した意味が無いので、
    サマリー表示でフラグを立てる。方向のシグナルではないことに注意。
    """

    def _series(self, values):
        import pandas as pd
        idx = pd.date_range("2025-01-01", periods=len(values), freq="B")
        return pd.Series(values, index=idx)

    def test_quiet_series_is_not_flagged(self):
        from update_data import unusual_move_z
        s = self._series([100.0 + (i % 2) * 0.1 for i in range(300)])
        assert unusual_move_z(s) is None

    def test_large_last_move_is_flagged(self):
        from update_data import unusual_move_z
        vals = [100.0 + (i % 2) * 0.1 for i in range(300)]
        vals.append(vals[-1] + 5.0)
        z = unusual_move_z(self._series(vals))
        assert z is not None
        assert z > 2.0

    def test_large_negative_move_is_flagged_with_sign(self):
        from update_data import unusual_move_z
        vals = [100.0 + (i % 2) * 0.1 for i in range(300)]
        vals.append(vals[-1] - 5.0)
        z = unusual_move_z(self._series(vals))
        assert z is not None
        assert z < -2.0

    def test_short_history_returns_none(self):
        """履歴が足りない系列で誤検出しない。"""
        from update_data import unusual_move_z
        assert unusual_move_z(self._series([100.0, 101.0, 102.0])) is None

    def test_zero_variance_history_returns_none(self):
        """全く動かない系列は標準偏差ゼロ。ゼロ除算で inf を返さない。"""
        from update_data import unusual_move_z
        s = self._series([100.0] * 300)
        assert unusual_move_z(s) is None

    def test_threshold_is_configurable(self):
        from update_data import unusual_move_z
        vals = [100.0 + (i % 2) * 0.1 for i in range(300)]
        vals.append(vals[-1] + 5.0)
        s = self._series(vals)
        assert unusual_move_z(s, sigma=100.0) is None
        assert unusual_move_z(s, sigma=1.0) is not None
