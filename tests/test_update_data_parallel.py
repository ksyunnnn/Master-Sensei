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
