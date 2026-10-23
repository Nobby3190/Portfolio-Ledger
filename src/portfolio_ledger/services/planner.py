"""Planning maths: FIRE projection (with life-plan events), loans, rebalancing, XIRR. Pure functions.

Projections use floats: they are estimates over decades, not ledger amounts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date


@dataclass
class Loan:
    grace_payment: float  # monthly, interest only (0 when there is no grace period)
    payment: float  # monthly, equal instalments after the grace period
    grace_months: int
    months: int  # whole term, grace included
    total_interest: float

    def at(self, k: int) -> float:
        """Payment in month k (1-based) of the loan; 0 once it is paid off."""
        if k < 1 or k > self.months:
            return 0.0
        return self.grace_payment if k <= self.grace_months else self.payment


def amortize(principal: float, annual_rate: float, years: float, grace_years: float = 0) -> Loan:
    """Equal-instalment loan (本息平均攤還); interest only during the grace period. Rates are fractions."""
    months = max(1, round(years * 12))
    grace = min(max(0, round(grace_years * 12)), months - 1)
    n = months - grace
    r = annual_rate / 12
    pay = principal / n if r == 0 else principal * r / (1 - (1 + r) ** -n)
    grace_pay = principal * r
    return Loan(grace_pay, pay, grace, months, grace_pay * grace + pay * n - principal)


def payoff(balance: float, annual_rate: float, loan: Loan, k: int) -> tuple[int, float] | None:
    """(months, interest) to repay `balance`, paying loan.at(k), loan.at(k+1)... (its level payment once
    the term is over); None when the payment never covers the interest. Rates are fractions."""
    r = annual_rate / 12
    months, interest = 0, 0.0
    while balance > 0.5:
        if months >= 1200:
            return None
        pay = loan.at(k + months) or loan.payment
        due = balance * r
        if pay <= due and k + months > loan.grace_months:  # past the grace period and still not shrinking
            return None
        interest += due
        balance -= min(balance, max(0.0, pay - due))
        months += 1
    return months, interest


@dataclass
class PlanEvent:
    """A big purchase in the projection, all in today's money."""

    month: int  # months from now (1 = next month)
    lump: float  # down payment + one-off costs, paid that month
    loan: Loan | None = None  # payments start the month after; fixed in nominal terms
    extra_monthly: float = 0.0  # running cost minus rent saved, from the month after


@dataclass
class FireResult:
    target: float  # annual spending / withdrawal rate (after every event)
    months_to_target: int | None  # None: not reached within the horizon
    series: list[tuple[int, float]]  # (year from now, projected assets in today's money)


def fire(
    current: float,
    monthly: float,
    annual_return: float,
    inflation: float,
    annual_spend: float,
    withdrawal_rate: float,
    horizon_years: int = 50,
    events: list[PlanEvent] | None = None,
) -> FireResult:
    """Grow `current` with `monthly` contributions at the real (inflation-adjusted) return.

    Rates are fractions (0.06 = 6%). Contributions stay flat in today's money. Events take their lump
    out in their month; afterwards loan payments (deflated, since they are fixed in nominal terms) and
    the extra running cost come out of the contributions, and the extra cost also raises the target.
    """
    events = events or []
    real = (1 + annual_return) / (1 + inflation) - 1
    m = (1 + real) ** (1 / 12) - 1
    deflate = (1 + inflation) ** (1 / 12)

    def target_at(month: int) -> float:
        spend = annual_spend + 12 * sum(e.extra_monthly for e in events if e.month < month)
        return spend / withdrawal_rate if withdrawal_rate > 0 else float("inf")

    value = current
    reached = 0 if value >= target_at(0) else None
    series = [(0, value)]
    for month in range(1, horizon_years * 12 + 1):
        out = 0.0
        for e in events:
            if e.month == month:
                out += e.lump
            elif e.month < month:
                k = month - e.month
                out += e.extra_monthly
                if e.loan:
                    out += e.loan.at(k) / deflate**k
        value = value * (1 + m) + monthly - out
        if reached is None and value >= target_at(month):
            reached = month
        if month % 12 == 0:
            series.append((month // 12, value))
    return FireResult(target_at(horizon_years * 12 + 1), reached, series)


@dataclass
class RebalanceRow:
    label: str
    value: float
    current: float  # share 0–1
    target: float  # share 0–1
    trade: float  # TWD to buy (+) or sell (−) to reach the target


def rebalance(values: dict[str, float], targets: dict[str, float]) -> list[RebalanceRow]:
    """values: TWD per class; targets: percent per class (normalised, so 70/20/10 or 7/2/1 both work)."""
    total = sum(values.values())
    tsum = sum(targets.values()) or 1
    rows = []
    for label in targets.keys() | values.keys():
        v = values.get(label, 0.0)
        t = targets.get(label, 0.0) / tsum
        rows.append(RebalanceRow(label, v, v / total if total else 0.0, t, t * total - v))
    order = list(targets)
    rows.sort(key=lambda r: order.index(r.label) if r.label in order else len(order))
    return rows


def xirr(flows: list[tuple[Date, float]]) -> float | None:
    """Annualised internal rate of return of dated cash flows (bisection; robust, no derivative)."""
    if not flows or not any(f < 0 for _, f in flows) or not any(f > 0 for _, f in flows):
        return None
    t0 = min(d for d, _ in flows)

    def npv(r: float) -> float:
        return sum(f / (1 + r) ** ((d - t0).days / 365.0) for d, f in flows)

    lo, hi = -0.99, 1e4
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            break
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def shift_month(month: str, n: int) -> str:
    """YYYY-MM moved by n months."""
    y, m = int(month[:4]), int(month[5:7])
    m += n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def months_between(start: Date, end: Date) -> int:
    """Whole months from start to end, at least 0."""
    return max(0, (end.year - start.year) * 12 + end.month - start.month - (end.day < start.day))
