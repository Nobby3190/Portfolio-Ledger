"""股利: the last 12 months' cash dividends, yield on cost, and the tax taken from a dividend.
Pure functions; ledger/finance gather the inputs (DESIGN.md「v1.4」股利).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date
from datetime import timedelta
from decimal import ROUND_FLOOR, Decimal

from ..models import TW_MARKETS
from . import fmt

ZERO = Decimal(0)

US_WITHHOLDING = Decimal("0.30")  # US tax withheld from dividends paid to non-residents
NHI_RATE = Decimal("0.0211")  # 二代健保補充保費
NHI_MIN = Decimal(20000)  # charged on a single payment of at least this much
NHI_MAX = Decimal(10_000_000)  # and on at most this much of it


def dividend_tax(gross: Decimal, market: str, currency: str) -> tuple[Decimal, str | None]:
    """(amount taken, what it is) from a gross dividend in the paying account's currency.

    Taiwan: 二代健保 2.11% on a payment of NT$ 20,000 or more, truncated to the dollar.
    US: 30% withholding. Other markets differ by company, so nothing (the user writes 稅).
    """
    if market in TW_MARKETS:
        if currency != "TWD" or gross < NHI_MIN:
            return ZERO, None
        return (min(gross, NHI_MAX) * NHI_RATE).to_integral_value(rounding=ROUND_FLOOR), "二代健保"
    if market == "US":
        return fmt.round_money(gross * US_WITHHOLDING, currency), "預扣稅"
    return ZERO, None


@dataclass
class Paid:
    date: str
    symbol: str
    twd: Decimal


@dataclass
class Summary:
    ttm: Decimal  # last 365 days
    ytd: Decimal  # this calendar year
    by_symbol: list[tuple[str, Decimal]] = field(default_factory=list)  # last 365 days, largest first
    yield_on_cost: Decimal | None = None  # ttm of open holdings that paid ÷ their cost
    cover: Decimal | None = None  # ttm ÷ a year of spending


def ttm_start(today: Date) -> str:
    return (today - timedelta(days=365)).isoformat()


def summarize(paid: list[Paid], open_cost: dict[str, Decimal], annual_spend: Decimal | None, today: Date) -> Summary:
    """open_cost: TWD cost of each symbol still held."""
    start, year = ttm_start(today), today.isoformat()[:4]
    by: dict[str, Decimal] = {}
    ytd = ZERO
    for p in paid:
        if p.date > today.isoformat():
            continue
        if p.date > start:
            by[p.symbol] = by.get(p.symbol, ZERO) + p.twd
        if p.date[:4] == year:
            ytd += p.twd
    ttm = sum(by.values(), ZERO)
    payers = [s for s in by if s in open_cost]
    cost = sum((open_cost[s] for s in payers), ZERO)
    paid_open = sum((by[s] for s in payers), ZERO)
    return Summary(
        ttm=ttm,
        ytd=ytd,
        by_symbol=sorted(by.items(), key=lambda kv: kv[1], reverse=True),
        yield_on_cost=paid_open / cost if cost > 0 else None,
        cover=ttm / annual_spend if annual_spend and annual_spend > 0 and ttm > 0 else None,
    )
