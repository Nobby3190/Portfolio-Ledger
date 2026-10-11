from decimal import Decimal as D

import pytest

from portfolio_ledger.models import Tx
from portfolio_ledger.services.portfolio import PortfolioError, replay

CUR = {1: "TWD", 2: "USD"}


def fx(cur, day):
    return D(30)


def tx(i, day, kind, sym=None, qty=None, price=None, amount=0, acc=1, fx_rate=None):
    return Tx(i, acc, day, kind, sym, D(qty) if qty is not None else None, D(price) if price else None,
              D(amount), fx_rate=D(fx_rate) if fx_rate else None)


def test_average_cost_partial_sell():
    book = replay([
        tx(1, "2026-01-01", "deposit", amount=300000),
        tx(2, "2026-01-02", "buy", "2330", 100, 1000, -100142),
        tx(3, "2026-02-01", "buy", "2330", 100, 1200, -120171),
        tx(4, "2026-03-01", "sell", "2330", 50, 1300, 64623),
    ], CUR, fx)
    p = book.positions[(1, "2330")]
    assert p.qty == 150
    assert p.avg_cost == D("1101.565")  # (100142 + 120171) / 200
    assert p.realized == D(64623) - D("55078.25")
    assert book.cash[1] == D(300000 - 100142 - 120171 + 64623)


def test_sell_all_then_buy_resets_cost():
    book = replay([
        tx(1, "2026-01-02", "buy", "0050", 3, 100, -320),
        tx(2, "2026-01-03", "sell", "0050", 3, 110, 300),
        tx(3, "2026-01-04", "buy", "0050", 1, 120, -140),
    ], CUR, fx)
    p = book.positions[(1, "0050")]
    assert (p.qty, p.cost, p.realized) == (D(1), D(140), D(-20))


def test_stock_dividend_and_split_keep_total_cost():
    book = replay([
        tx(1, "2026-01-02", "buy", "2884", 1000, 30, -30042),
        tx(2, "2026-07-01", "stock_dividend", "2884", 50),
        tx(3, "2026-08-01", "split", "2884", 2),
    ], CUR, fx)
    p = book.positions[(1, "2884")]
    assert p.qty == 2100 and p.cost == 30042


def test_oversell_raises():
    with pytest.raises(PortfolioError, match="只持有 10 股"):
        replay([tx(1, "2026-01-02", "buy", "2330", 10, 1, -30), tx(2, "2026-01-03", "sell", "2330", 11, 1, 1)], CUR, fx)


def test_usd_position_uses_fx_at_trade():
    book = replay([
        tx(1, "2026-01-02", "buy", "VOO", 10, 500, -5000, acc=2, fx_rate="30"),
        tx(2, "2026-06-01", "sell", "VOO", 5, 600, 3000, acc=2, fx_rate="32"),
        tx(3, "2026-07-01", "cash_dividend", "VOO", amount=10, acc=2),  # no stored rate -> lookup (30)
    ], CUR, fx)
    p = book.positions[(2, "VOO")]
    assert p.cost_twd == D(75000)
    assert p.realized == D(500)
    assert p.realized_twd == D(3000 * 32 - 75000)  # price gain and FX gain together
    assert p.dividends_twd == D(300)
