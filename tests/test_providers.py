import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from portfolio_ledger.providers.base import ProviderError, roc_date
from portfolio_ledger.providers.twse import parse_tpex, parse_twse
from portfolio_ledger.providers.yahoo import parse_chart

F = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((F / name).read_text())


def test_roc_date():
    assert roc_date("1151008") == "2026-10-08"
    assert roc_date("991231") == "2010-12-31"
    assert roc_date("") is None


def test_twse_filters_and_parses():
    secs = {s.symbol: s for s in parse_twse(load("twse.json"))}
    assert set(secs) == {"0050", "2330", "9999"}  # warrant dropped
    tsmc = secs["2330"]
    assert (tsmc.last_close, tsmc.prev_close, tsmc.last_date) == (D("2550.00"), D("2585.0000"), "2026-10-08")
    assert secs["0050"].kind == "etf"
    assert secs["9999"].last_close is None and secs["9999"].last_date is None


def test_tpex_commas_and_plus_sign():
    secs = {s.symbol: s for s in parse_tpex(load("tpex.json"))}
    assert set(secs) == {"00679B", "6488"}
    assert secs["6488"].last_close == D("1020.00")
    assert secs["00679B"].prev_close == D("27.38") and secs["00679B"].kind == "bond_etf"
    assert secs["6488"].market == "TPEX"


def test_yahoo_chart():
    h = parse_chart(load("yahoo_voo.json"), "VOO")
    assert h.name == "Vanguard S&P 500 ETF" and h.kind == "etf" and h.currency == "USD"
    assert h.last == ("2026-10-09", D("715.59"))
    assert h.prev_close == D("710.87")
    assert len(h.closes) == 3  # the null close is skipped


def test_yahoo_unknown_symbol():
    with pytest.raises(ProviderError, match="找不到"):
        parse_chart(load("yahoo_404.json"), "ZZZZ")


def test_cathay_board():
    from portfolio_ledger.providers.cathay import parse_board

    day, rates = parse_board((F / "cathay_board.html").read_text())
    assert day == "2026-10-11"
    assert (rates["USD"].buy, rates["USD"].sell) == (D("31.8000"), D("32.0000"))
    assert (rates["CNY"].buy, rates["JPY"].buy) == (D("4.716"), D("0.1997"))
    assert {"EUR", "HKD", "AUD", "GBP", "SGD"} <= set(rates)


def test_cathay_board_layout_changed():
    from portfolio_ledger.providers.cathay import parse_board

    with pytest.raises(ProviderError):
        parse_board("<html>nothing here</html>")
