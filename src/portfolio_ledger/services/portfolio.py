"""Replay transactions into positions and cash. Nothing here touches the database.

Cost basis is the average-cost method: buy fees go into cost; a sale removes
qty × average cost and books the rest as realized P&L. Every TWD figure uses the
FX rate stored on the transaction (or the day's rate), so a USD holding's TWD
P&L includes the currency move.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from ..models import Tx
from .fmt import qty as fmt_qty

ZERO = Decimal(0)

# (currency, date) -> TWD per unit
FxLookup = Callable[[str, str], Decimal]


class PortfolioError(ValueError):
    pass


@dataclass
class Position:
    account_id: int
    symbol: str
    qty: Decimal = ZERO
    cost: Decimal = ZERO  # account currency, includes buy fees
    cost_twd: Decimal = ZERO
    realized: Decimal = ZERO
    realized_twd: Decimal = ZERO
    dividends: Decimal = ZERO
    dividends_twd: Decimal = ZERO
    sold_cost_twd: Decimal = ZERO  # cost basis already closed out, for the overall return %
    tx_ids: list[int] = field(default_factory=list)
    # TWD money in (−) and out (+) of this position by date, for the annualized return (XIRR).
    flows: list[tuple[str, Decimal]] = field(default_factory=list)

    @property
    def avg_cost(self) -> Decimal:
        return self.cost / self.qty if self.qty else ZERO


@dataclass
class Book:
    positions: dict[tuple[int, str], Position]
    cash: dict[int, Decimal]  # account id -> balance in account currency
    # Foreign-currency accounts: TWD cost of the cash balance (average cost, like a position).
    cash_cost_twd: dict[int, Decimal] = field(default_factory=dict)

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if p.qty != 0]


def replay(txs: Iterable[Tx], currency_of: dict[int, str], fx: FxLookup) -> Book:
    """txs must be sorted by (date, id). Raises PortfolioError on overselling."""
    positions: dict[tuple[int, str], Position] = {}
    cash: dict[int, Decimal] = {aid: ZERO for aid in currency_of}

    cash_cost: dict[int, Decimal] = {}

    for t in txs:
        cur = currency_of.get(t.account_id, "TWD")
        if cur == "TWD":
            rate = Decimal(1)  # a TWD account's fx_rate, when set, is a 台幣交割 conversion rate, not this
        else:
            rate = t.fx_rate if t.fx_rate is not None else fx(cur, t.date)
        conversion = t.fx_rate if cur == "TWD" and t.fx_rate is not None else None
        before = cash.get(t.account_id, ZERO)
        cash[t.account_id] = before + t.amount
        if cur != "TWD" and t.amount:
            cost = cash_cost.get(t.account_id, ZERO)
            if t.amount > 0:
                cost += t.amount * rate
            elif before > 0:
                cost -= cost * min(Decimal(1), -t.amount / before)
            cash_cost[t.account_id] = cost
        if t.symbol is None:
            continue
        key = (t.account_id, t.symbol)
        p = positions.get(key)
        if p is None:
            p = positions[key] = Position(t.account_id, t.symbol)
        if t.id is not None:
            p.tx_ids.append(t.id)
        qty = t.qty or ZERO

        if t.kind == "buy":
            cost = -t.amount  # gross + fee
            p.qty += qty
            p.cost += cost
            p.cost_twd += cost * rate
            p.flows.append((t.date, -cost * rate))
        elif t.kind == "holding_in":
            # Backfilled purchase: cash untouched, cost = what was paid (TWD amounts truncated like a buy).
            gross = qty * (t.price or ZERO)
            if conversion is not None:  # 台幣交割: foreign price × the conversion rate, whole TWD
                gross = (gross * conversion).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            elif cur == "TWD":
                gross = gross.to_integral_value(rounding=ROUND_FLOOR)
            cost = gross + t.fee + t.tax
            p.qty += qty
            p.cost += cost
            p.cost_twd += cost * rate
            p.flows.append((t.date, -cost * rate))
        elif t.kind == "sell":
            if qty > p.qty:
                raise PortfolioError(f"{t.date} 賣出 {t.symbol} {fmt_qty(qty)} 股，但當時只持有 {fmt_qty(p.qty)} 股")
            share = qty / p.qty
            out, out_twd = p.cost * share, p.cost_twd * share
            p.qty -= qty
            p.cost -= out
            p.cost_twd -= out_twd
            p.realized += t.amount - out
            p.realized_twd += t.amount * rate - out_twd
            p.sold_cost_twd += out_twd
            p.flows.append((t.date, t.amount * rate))
            if p.qty == 0:  # avoid dust from the division above
                p.cost = p.cost_twd = ZERO
        elif t.kind == "cash_dividend":
            p.dividends += t.amount
            p.dividends_twd += t.amount * rate
            p.flows.append((t.date, t.amount * rate))
        elif t.kind == "stock_dividend":
            p.qty += qty
        elif t.kind == "split":
            p.qty *= qty
    return Book(positions, cash, cash_cost)

