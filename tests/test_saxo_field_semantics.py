"""Saxo API field の「意味」を実測 payload に対して固定する (ADR-026)

## なぜこのファイルがあるか

ADR-026 は `docs/api/<provider>/` に公式仕様を citation することを要求しているが、
**その解釈が実データと合っているかの検証は要求していなかった**。結果、
`docs/api/saxo/balance-fields.md` は `UnrealizedPositionsValue` の公式定義
("The current unrealized profit/loss and face value...") を正しく引用したうえで、
その直下に「含み損益確認」という誤った解釈行を書いていた。誤りは 2026-09-01 に
実測するまで検出されなかった (2026-04 の初回コミットから無修正)。

公式定義の引用は解釈の検証にならない。定義文が曖昧・複合的な場合はなおさら
(上記の "profit/loss **and face value**" は実際には face value 側が主)。

## このファイルの規律

field の意味は**恒等式**として書く。「A は B である」ではなく
「A == f(C, D) が実測 payload 上で成立する」を assert する。恒等式が壊れたら
Saxo 側の仕様変更か、こちらの解釈違いのどちらかであり、どちらも検出したい。

fixture は `tests/fixtures/saxo_live_snapshot_20260901.json`。
live 口座から採取した生 payload で、秘匿 field のみ REDACTED 済み。
新しい建玉状態 (複数建玉・margin 建玉・market open 時) を観測したら
fixture を追加し、同じ恒等式が成立するか確かめること。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "saxo_live_snapshot_20260901.json"

# CurrencyDecimals=0 の JPY 口座では整数丸めが入るため、円単位の恒等式は 1 円許容する
JPY_ROUNDING_TOL = 1.0


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def balance(snapshot) -> dict:
    return snapshot["balance"]


@pytest.fixture(scope="module")
def position_view(snapshot) -> dict:
    return snapshot["position"]["PositionView"]


@pytest.fixture(scope="module")
def position_base(snapshot) -> dict:
    return snapshot["position"]["PositionBase"]


class TestUnrealizedPositionsValueIsNotProfitLoss:
    """`UnrealizedPositionsValue` は含み損益ではなく「時価 - 決済コスト」

    2026-09-01 の実測: 口座 T126816 は SOXL 25株を建値 $119.879 で持ち、
    含み損益は -28,200 円。同時刻の `UnrealizedPositionsValue` は +449,931 円で、
    符号も桁も違う (差 478,131 円)。名前から含み損益と読むと 47.8 万円ぶん
    逆向きに誤る。
    """

    def test_equals_market_value_minus_cost_to_close(self, balance):
        # CostToClosePositions は負値で入る (決済にかかるコスト)
        expected = balance["NonMarginPositionsValue"] + balance["CostToClosePositions"]
        assert balance["UnrealizedPositionsValue"] == pytest.approx(
            expected, abs=JPY_ROUNDING_TOL
        )

    def test_excluding_cost_variant_equals_market_value(self, balance):
        assert balance["UnrealizedPositionsValueExcludingCostToClosePositions"] == (
            pytest.approx(balance["NonMarginPositionsValue"], abs=JPY_ROUNDING_TOL)
        )

    def test_is_not_the_position_profit_loss(self, balance, position_view):
        """反証条件: 含み損益だとする解釈が成立しないことを明示的に固定する"""
        pnl = position_view["ProfitLossOnTradeInBaseCurrency"]
        assert balance["UnrealizedPositionsValue"] != pytest.approx(pnl, abs=1000.0)
        # 符号すら違う。含み損なのに正値が返る
        assert pnl < 0 < balance["UnrealizedPositionsValue"]

    def test_total_value_is_cash_plus_positions(self, balance):
        assert balance["TotalValue"] == pytest.approx(
            balance["CashBalance"] + balance["NonMarginPositionsValue"],
            abs=JPY_ROUNDING_TOL,
        )


class TestBaseCurrencyPnlExcludesFx:
    """`ProfitLossOnTradeInBaseCurrency` は**建玉時**の為替レートで換算される

    したがって為替変動ぶんが入っていない。円で見た本当の含み損益を出すには
    `ProfitLossCurrencyConversion` を足す必要がある。
    K-066 は実現損益について同じ穴を記録済みだが、含み損益側は未記録だった。

    2026-09-01 実測: ProfitLossOnTradeInBaseCurrency = -28,200 円 に対し、
    円ベースの実際の含み損益は -27,218 円 (FX ぶん +1,022 円)。
    """

    def test_uses_open_conversion_rate_not_current(self, position_view):
        pnl_usd = position_view["ProfitLossOnTrade"]
        pnl_base = position_view["ProfitLossOnTradeInBaseCurrency"]

        assert pnl_base == pytest.approx(
            pnl_usd * position_view["ConversionRateOpen"], abs=5.0
        )
        # 現在レート換算とは一致しない = FX 変動が除外されている証拠
        assert pnl_base != pytest.approx(
            pnl_usd * position_view["ConversionRateCurrent"], abs=5.0
        )

    def test_true_jpy_pnl_needs_currency_conversion_term(self, balance, position_view):
        """円建て口座での本当の含み損益 = 現在の時価(円) - 取得原価(円)"""
        # MarketValueOpenInBaseCurrency は負値 (取得に支払った額)
        true_jpy_pnl = (
            balance["NonMarginPositionsValue"]
            + position_view["MarketValueOpenInBaseCurrency"]
        )
        reported = (
            position_view["ProfitLossOnTradeInBaseCurrency"]
            + position_view["ProfitLossCurrencyConversion"]
        )
        assert true_jpy_pnl == pytest.approx(reported, abs=100.0)

        # 素の ProfitLossOnTradeInBaseCurrency だけでは 1,000 円近くずれる
        naive = position_view["ProfitLossOnTradeInBaseCurrency"]
        assert abs(true_jpy_pnl - naive) > 900.0


class TestClosedMarketPriceFieldsAreZero:
    """market closed かつ購読なしのとき、現値系 field は 0.0 で返る

    `CurrentPrice` / `MarketValue` / `Exposure` が 0.0 になる。これらを現値として
    使うと、割り算は ZeroDivisionError、比較は黙って誤った判定になる。
    `CalculationReliability` が "Ok" 以外 (ここでは "ApproximatedPrice") の時は
    現値系を信用しない、が唯一の安全な読み方。

    含み損益 (`ProfitLossOnTrade`) の方は 0 にならず、近似価格で計算されている
    (逆算すると $112.7998 = 2026-08-31 終値 $112.79)。つまり
    「現値は取れないが損益は出る」という非対称がある。
    """

    def test_current_price_is_zero_when_market_closed(self, position_view):
        assert position_view["MarketState"] == "Closed"
        assert position_view["CurrentPrice"] == 0.0
        assert position_view["MarketValue"] == 0.0
        assert position_view["Exposure"] == 0.0

    def test_calculation_reliability_flags_the_approximation(self, position_view):
        assert position_view["CalculationReliability"] != "Ok"
        assert position_view["CurrentPriceType"] == "None"

    def test_profit_loss_is_still_populated_from_approximated_price(
            self, position_view, position_base):
        """現値 0 でも損益は非ゼロ。近似価格が使われている"""
        assert position_view["ProfitLossOnTrade"] != 0.0

        implied_price = (
            position_base["OpenPrice"]
            + position_view["ProfitLossOnTrade"] / position_base["Amount"]
        )
        # 2026-08-31 の SOXL 終値 112.79 に一致する
        assert implied_price == pytest.approx(112.79, abs=0.02)


class TestOpenPriceExcludesCosts:
    """`OpenPrice` は約定価格そのもの。コスト込みは `OpenPriceIncludingCosts`

    判断層 `trades` に建値として記録するのはどちらかを取り違えると、
    含み損益と損益分岐が commission ぶんずれる。
    """

    def test_two_open_prices_differ_by_costs(self, position_base):
        raw = position_base["OpenPrice"]
        incl = position_base["OpenPriceIncludingCosts"]
        assert incl > raw
        assert incl - raw == pytest.approx(0.1056, abs=0.0005)


class TestDocumentedFieldsCoverPayload:
    """payload に出る field が balance-fields.md に記載されているか

    未記載の field があると、次にそれを読むときまた推測から始まる。
    新しい field を観測したら doc に追記してからこのリストを更新する。
    """

    # 2026-09-01 時点で payload に存在するが doc の ### 見出しに無い field。
    # doc に追記したらここから消す。
    KNOWN_UNDOCUMENTED: set[str] = set()

    def test_no_new_undocumented_fields(self, balance):
        doc = (
            Path(__file__).parent.parent
            / "docs" / "api" / "saxo" / "balance-fields.md"
        ).read_text()
        # 見出しは "### Foo" または "### Foo / Bar / Baz" の複合形を取る
        documented: set[str] = set()
        for line in doc.splitlines():
            if line.startswith("### "):
                for part in line[4:].split("/"):
                    documented.add(part.strip())

        undocumented = {k for k in balance if k not in documented}
        assert undocumented == self.KNOWN_UNDOCUMENTED, (
            f"balance payload に doc 未記載の field がある: "
            f"{sorted(undocumented - self.KNOWN_UNDOCUMENTED)}. "
            f"docs/api/saxo/balance-fields.md に公式定義を追記し、"
            f"意味は恒等式としてこのファイルに固定すること"
        )
