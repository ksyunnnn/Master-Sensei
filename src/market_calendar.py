"""NYSE の営業日カレンダー (祝日を含む)。

「その時点で確定しているレギュラー終値はどの日のものか」を決めるために使う。
週末だけを除く素朴な営業日計算は、祝日の翌営業日に「データが1日古い」と誤検知する。
誤検知した警告はデータを更新しても消えないため、読み手が警告を無視する習慣を作る
(ADR-031 の stale 検知が自壊する)。

依存を増やさず自前で持つ方針。NYSE の規則は決定的なので計算できる:

- 固定日 (元日/Juneteenth/独立記念日/クリスマス) は土曜なら前金曜、日曜なら翌月曜に振替
- 移動祝日 (MLK/大統領/メモリアル/レイバー/感謝祭) は第N週の曜日
- グッドフライデー は復活祭の2日前 (復活祭は Meeus/Jones/Butcher のアルゴリズムで算出)

規則で導けない臨時休場 (国葬・災害) は既知ぶんを `_AD_HOC_CLOSURES` に列挙する。
将来の臨時休場は誰にも予測できないため、発生した翌営業日は「1営業日古い」と誤検知する。
その時はこの集合に日付を追加する (SPY の日足 parquet と突き合わせれば検出できる)。

半日立会い (13:00 ET 引け) は対象外。終値が存在する日なので営業日として正しく、
乖離の基準日としても問題にならない。
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

# NYSE が Juneteenth を休場にしたのは 2022年から。
_JUNETEENTH_FIRST_YEAR = 2022

# 規則で導けない臨時休場 (実績)。SPY 日足 parquet (2021-06以降) と突合して検証済み。
_AD_HOC_CLOSURES = frozenset({
    date(2025, 1, 9),    # カーター元大統領の国葬
    date(2018, 12, 5),   # ブッシュ元大統領の国葬
    date(2012, 10, 29),  # ハリケーン・サンディ
    date(2012, 10, 30),  # ハリケーン・サンディ
    date(2007, 1, 2),    # フォード元大統領の国葬
    date(2004, 6, 11),   # レーガン元大統領の国葬
    date(2001, 9, 11),   # 同時多発テロ
    date(2001, 9, 12),
    date(2001, 9, 13),
    date(2001, 9, 14),
})


def _easter_sunday(year: int) -> date:
    """復活祭の日曜 (Meeus/Jones/Butcher のグレゴリオ暦アルゴリズム)。"""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """その月の第n weekday (weekday: 月=0 ... 日=6)。"""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """その月の最終 weekday。"""
    if month == 12:
        d = date(year, 12, 31)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """固定日祝日の振替。土曜→前金曜、日曜→翌月曜 (NYSE 規則)。"""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def nyse_holidays(year: int) -> frozenset:
    """その年の NYSE 休場日 (振替後の実際の休場日)。"""
    days = {
        _observed(date(year, 1, 1)),                 # 元日
        _nth_weekday(year, 1, 0, 3),                 # キング牧師記念日 (第3月)
        _nth_weekday(year, 2, 0, 3),                 # 大統領の日 (第3月)
        _easter_sunday(year) - timedelta(days=2),    # グッドフライデー
        _last_weekday(year, 5, 0),                   # メモリアルデー (最終月)
        _observed(date(year, 7, 4)),                 # 独立記念日
        _nth_weekday(year, 9, 0, 1),                 # レイバーデー (第1月)
        _nth_weekday(year, 11, 3, 4),                # 感謝祭 (第4木)
        _observed(date(year, 12, 25)),               # クリスマス
    }
    if year >= _JUNETEENTH_FIRST_YEAR:
        days.add(_observed(date(year, 6, 19)))       # ジューンティーンス
    days |= {d for d in _AD_HOC_CLOSURES if d.year == year}
    return frozenset(days)


def is_trading_day(d: date) -> bool:
    """レギュラー立会いがある日か (土日・祝日・既知の臨時休場でない)。"""
    if d.weekday() >= 5:
        return False
    return d not in nyse_holidays(d.year)


def previous_trading_day(d: date) -> date:
    """d より前で直近の営業日。"""
    day = d - timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day


def trading_days_between(start: date, end: date) -> int:
    """start から end までの営業日数 (土日・祝日を除く)。end <= start なら 0。

    基準がデータ側で先行している場合 (end < start) は stale ではないので 0。
    """
    if end <= start:
        return 0
    n = 0
    d = start
    while d < end:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return n
