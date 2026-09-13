"""残存建玉の導出と評価 (純ロジック、I/O なし)。

執行事実層 account_transactions (ADR-030) の約定行から「今いくつ持っていて、
取得原価はいくらか」を FIFO で導出し、現値で評価する。DuckDB / Parquet /
ネットワークには触らないので、テストは行のリストだけで完結する。

**取得原価は台帳の `amount`(手数料込みの記帳額)を使う**。`price_per_unit *
quantity` では手数料が落ち、建値が実際より低く出て含み損益を過大評価する。
決済を net で語る方針 (docs/trading-notes.md の KPI 方針、K-041) と基準を揃える。

**FIFO で古い lot から消し込む**。決済済みの lot を平均に混ぜると建値が汚染される。
前例: 2026-08-18 に $134.13 で買った 24株は 8/19 に決済済みで、残る 25株の建値
$120.194 とは無関係。平均法だと $127 前後の存在しない建値になる。

なお Saxo ライブ建玉の `open_price` は手数料を含まないため、ここで出す建値とは
1株あたり数セント単位でずれる (25株で $7.86 = $0.315/株 の実測)。同じ建玉でも
出所が違えば建値が違うので、表示には必ず出所を添える。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional


@dataclass(frozen=True)
class LedgerFill:
    """台帳の約定1行のうち、建玉計算に要る field だけを取り出したもの。

    台帳の生 dict をそのまま持ち回すと、呼び出し側がキー名を推測して壊れる
    (ADR-026)。数量・金額の符号規約をここで1か所に固定する。

    Attributes:
        instrument: 銘柄コード。
        side: 'buy' | 'sell'。それ以外 (deposit 等) は呼び出し前に除外する。
        quantity: 数量。常に正。
        amount: 記帳額。買い=負 (出金) / 売り=正 (入金)、手数料込み。
        trade_date: 約定日。
    """
    instrument: str
    side: str
    quantity: float
    amount: float
    trade_date: date


@dataclass(frozen=True)
class LedgerPosition:
    """台帳から導出した残存建玉。

    Attributes:
        instrument: 銘柄コード。
        quantity: 残存数量。
        cost_usd: 残存分の取得原価 (手数料込み、正)。
        avg_price: cost_usd / quantity。手数料込みの実効建値。
        opened_on: 残っている最古 lot の約定日 (保有日数の起点)。
    """
    instrument: str
    quantity: float
    cost_usd: float
    avg_price: float
    opened_on: date


@dataclass(frozen=True)
class PositionValuation:
    """建玉 + 現値 = 含み損益。

    Attributes:
        position: 評価対象の建玉。
        mark: 評価に使った1株あたり価格。
        mark_label: mark の出所 ('9/10終値' / 'pre 118.10' 等)。出所を値と一緒に
            持ち歩かないと、stale な終値を現値と読み違える (ADR-031)。
        market_value_usd: mark * quantity。
        pnl_usd: market_value_usd - cost_usd。
        pnl_pct: cost_usd に対する率 (%)。ドル額と必ず併記する (CLAUDE.md Rules)。
    """
    position: LedgerPosition
    mark: float
    mark_label: str
    market_value_usd: float
    pnl_usd: float
    pnl_pct: float


class _OpenLot:
    """FIFO 消し込み中の可変 lot。fifo_open_lots の内部専用。"""

    __slots__ = ("quantity", "cost_usd", "trade_date")

    def __init__(self, quantity: float, cost_usd: float, trade_date: date):
        self.quantity = quantity
        self.cost_usd = cost_usd
        self.trade_date = trade_date

    def consume(self, quantity: float) -> float:
        """先頭から quantity ぶん取り崩し、取り崩せなかった残りを返す。

        原価は数量按分で減らす。1 lot を部分決済した時に、残り数量ぶんの原価だけが
        残るようにするため。
        """
        taken = min(self.quantity, quantity)
        self.cost_usd -= self.cost_usd * (taken / self.quantity)
        self.quantity -= taken
        return quantity - taken


def fifo_open_lots(fills: Iterable[LedgerFill]) -> dict[str, LedgerPosition]:
    """約定列を FIFO で畳み込み、instrument ごとの残存建玉を返す。

    fills は **約定順に並んでいること**を前提とする (同日は買い→売り)。並べ替えは
    読み出し側 (SQL の ORDER BY) の責務。ここで並べ替えると、台帳の順序保証が
    2か所に散る。

    在庫を超える売り (台帳の取り込み漏れ・空売り) は残数量を負にせず、消し込め
    なかったぶんを捨てる。負の建玉を表示すると「持っていないものを持っている」と
    読めてしまうため。数量の不整合検出は reconcile_positions の責務 (ADR-030)。

    Returns:
        {instrument: LedgerPosition}。残数量が 0 の instrument は含めない。
    """
    lots: dict[str, list[_OpenLot]] = {}

    for fill in fills:
        queue = lots.setdefault(fill.instrument, [])
        if fill.side == "buy":
            queue.append(_OpenLot(fill.quantity, abs(fill.amount), fill.trade_date))
            continue
        remaining = fill.quantity
        while remaining > 0 and queue:
            remaining = queue[0].consume(remaining)
            if queue[0].quantity <= 0:
                queue.pop(0)

    positions: dict[str, LedgerPosition] = {}
    for instrument, queue in lots.items():
        quantity = sum(lot.quantity for lot in queue)
        if quantity <= 0:
            continue
        cost_usd = sum(lot.cost_usd for lot in queue)
        positions[instrument] = LedgerPosition(
            instrument=instrument,
            quantity=quantity,
            cost_usd=cost_usd,
            avg_price=cost_usd / quantity,
            opened_on=queue[0].trade_date,
        )
    return positions


def value_position(
    position: LedgerPosition, mark: float, mark_label: str
) -> PositionValuation:
    """建玉を mark で評価する。

    Args:
        position: 評価対象。
        mark: 1株あたり価格。
        mark_label: mark の出所。値だけ渡して出所を捨てると、終値か現値かが
            表示から失われる (ADR-031)。

    Raises:
        ValueError: mark_label が空。出所不明の評価値は表示させない。
    """
    if not mark_label:
        raise ValueError("mark_label is required: 評価値には出所を添える (ADR-031)")
    market_value_usd = mark * position.quantity
    pnl_usd = market_value_usd - position.cost_usd
    return PositionValuation(
        position=position,
        mark=mark,
        mark_label=mark_label,
        market_value_usd=market_value_usd,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_usd / position.cost_usd * 100.0,
    )


def format_valuation(v: PositionValuation, *, note: Optional[str] = None) -> str:
    """建玉1件の表示行。含み損益はドル額と % を必ず併記する (CLAUDE.md Rules)。"""
    sign = "+" if v.pnl_usd >= 0 else "-"
    pos = v.position
    line = (
        f"  {pos.instrument:<5s} {pos.quantity:g}株  "
        f"建値 ${pos.avg_price:.3f}  原価 ${pos.cost_usd:,.2f}  "
        f"({pos.opened_on.month}/{pos.opened_on.day:02d} 建)\n"
        f"        {v.mark_label} ${v.mark:.2f} → 評価 ${v.market_value_usd:,.2f}  "
        f"含み {sign}${abs(v.pnl_usd):,.2f} ({sign}{abs(v.pnl_pct):.2f}%)"
    )
    if note:
        line += f"  {note}"
    return line
