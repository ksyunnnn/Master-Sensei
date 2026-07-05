"""US 株式市場(NYSE/Nasdaq) 休場・短縮取引カレンダーの .ics 生成器.

出典: NYSE Group 公式 "2026, 2027 and 2028 Holiday and Early Closings Calendar"
(ICE/BusinessWire, 2025-12-23 発表) を一次情報として転記・検証したもの。
NYSE と Nasdaq は同一スケジュール。

このファイルが配信フィード calendar/us_market_holidays.ics の Source of Truth。
更新方法: 下の HOLIDAYS に新年分を追記 -> `python calendar/generate_holidays_ics.py` -> commit/push。
Google カレンダーは購読URLを定期再取得するので、push すれば自動で最新化される。

注意した非自明ルール:
- 土曜の祝日は前金曜に振替(例: 2026-07-03 独立記念日)。日曜は翌月曜(例: 2027-07-05)。
- ただし New Year だけは例外で、1/1 が土曜でも前年12/31を振替休にしない
  (2028-01-01 は土曜 -> 2028 は New Year 休場なし)。
- 独立記念日/感謝祭翌日/クリスマスイブ等が平日なら 13:00 ET 早引け。
"""
from __future__ import annotations

from datetime import date, timedelta

# (ISO date, 種別 'holiday'|'early', 表示名)
# NYSE 公式リリース(2026-2028)を転記。全 date は平日であること・件数を末尾で検算する。
HOLIDAYS: list[tuple[str, str, str]] = [
    # 2026
    ("2026-01-01", "holiday", "元日"),
    ("2026-01-19", "holiday", "キング牧師記念日(MLK)"),
    ("2026-02-16", "holiday", "ワシントン誕生日(Presidents' Day)"),
    ("2026-04-03", "holiday", "グッドフライデー"),
    ("2026-05-25", "holiday", "メモリアルデー"),
    ("2026-06-19", "holiday", "ジューンティーンス"),
    ("2026-07-03", "holiday", "独立記念日(振替: 7/4土)"),
    ("2026-09-07", "holiday", "レイバーデー"),
    ("2026-11-26", "holiday", "感謝祭"),
    ("2026-11-27", "early", "感謝祭翌日"),
    ("2026-12-24", "early", "クリスマスイブ"),
    ("2026-12-25", "holiday", "クリスマス"),
    # 2027
    ("2027-01-01", "holiday", "元日"),
    ("2027-01-18", "holiday", "キング牧師記念日(MLK)"),
    ("2027-02-15", "holiday", "ワシントン誕生日(Presidents' Day)"),
    ("2027-03-26", "holiday", "グッドフライデー"),
    ("2027-05-31", "holiday", "メモリアルデー"),
    ("2027-06-18", "holiday", "ジューンティーンス(振替: 6/19土)"),
    ("2027-07-05", "holiday", "独立記念日(振替: 7/4日)"),
    ("2027-09-06", "holiday", "レイバーデー"),
    ("2027-11-25", "holiday", "感謝祭"),
    ("2027-11-26", "early", "感謝祭翌日"),
    ("2027-12-24", "holiday", "クリスマス(振替: 12/25土)"),
    # 2028  (元日 1/1 は土曜 -> 振替なし = New Year 休場なし)
    ("2028-01-17", "holiday", "キング牧師記念日(MLK)"),
    ("2028-02-21", "holiday", "ワシントン誕生日(Presidents' Day)"),
    ("2028-04-14", "holiday", "グッドフライデー"),
    ("2028-05-29", "holiday", "メモリアルデー"),
    ("2028-06-19", "holiday", "ジューンティーンス"),
    ("2028-07-03", "early", "独立記念日前日"),
    ("2028-07-04", "holiday", "独立記念日"),
    ("2028-09-04", "holiday", "レイバーデー"),
    ("2028-11-23", "holiday", "感謝祭"),
    ("2028-11-24", "early", "感謝祭翌日"),
    ("2028-12-25", "holiday", "クリスマス"),
]

DTSTAMP = "20260705T000000Z"  # 生成基準(固定; 差分を安定させるためハードコード)
OUT = "calendar/us_market_holidays.ics"


def _fold(line: str) -> str:
    return line


def build() -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Master Sensei//US Market Holidays//JA",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:米株 休場・短縮 (NYSE/Nasdaq)",
        "X-WR-CALDESC:NYSE/Nasdaq の終日休場と13:00 ET早引け。出典NYSE公式。",
        "X-WR-TIMEZONE:America/New_York",
    ]
    for iso, kind, name in HOLIDAYS:
        d = date.fromisoformat(iso)
        assert d.weekday() < 5, f"{iso} が週末に落ちている(振替ミス): {name}"
        ymd = iso.replace("-", "")
        nxt = (d + timedelta(days=1)).isoformat().replace("-", "")
        if kind == "holiday":
            summary = f"[米株休場] {name} NYSE/Nasdaq"
            desc = "NYSE・Nasdaq 終日休場(公式スケジュール)。"
            cat = "Market Holiday"
        else:
            summary = f"[米株短縮] 13:00 ET早引け({name}) NYSE/Nasdaq"
            desc = "NYSE・Nasdaq 13:00 ET 短縮取引(=翌03:00 JST頃 close, EST)。オプションは13:15 ET。"
            cat = "Market Early Close"
        lines += [
            "BEGIN:VEVENT",
            f"UID:usmkt-{ymd}-{kind}@master-sensei",
            f"DTSTAMP:{DTSTAMP}",
            f"DTSTART;VALUE=DATE:{ymd}",
            f"DTEND;VALUE=DATE:{nxt}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{desc}",
            "TRANSP:TRANSPARENT",
            f"CATEGORIES:{cat}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


if __name__ == "__main__":
    ics = build()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(ics)
    n_hol = sum(1 for _, k, _ in HOLIDAYS if k == "holiday")
    n_early = sum(1 for _, k, _ in HOLIDAYS if k == "early")
    print(f"wrote {OUT}: {len(HOLIDAYS)} events (休場{n_hol} / 短縮{n_early})")
