"""投資健檢: rule-based checks on the user's own ledger. Pure functions; no database, no market data.

Texts are lists of segments: plain strings, and {"m": "84,000"} for TWD amounts so the page can hide
them in privacy mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from . import fmt

DEFAULT_THRESHOLDS = {
    "fund_min_months": 6,  # emergency fund: fewer months of spending → warn
    "fund_max_months": 12,  # more → note (idle cash)
    "drift_pct": 5,  # allocation drift in percentage points → note
    "stock_note_pct": 20,  # single stock share of investments → note
    "stock_warn_pct": 35,  # → warn
    "loan_note_pct": 30,  # loan payments share of income → note
    "loan_warn_pct": 40,  # → warn
    "savings_min_pct": 10,  # savings rate below → note
    "deposit_days": 30,  # time deposit maturing within → note
    "near_years": 3,  # plan spending within this many years should sit in cash
}

LEVELS = {"warn": 0, "note": 1, "ok": 2}

Seg = str | dict[str, str]


def m(x: float) -> dict[str, str]:
    """A TWD amount segment."""
    return {"m": fmt.money(Decimal(round(x))) or "0"}


@dataclass
class Holding:
    name: str
    value: float  # TWD
    is_fund: bool  # ETF / bond ETF: already diversified


@dataclass
class Need:
    name: str
    month: str  # YYYY-MM
    amount: float  # down payment + one-off costs still to pay


@dataclass
class Deposit:
    name: str
    days_left: int


@dataclass
class Inputs:
    liquid: float  # TWD cash in bank and cash accounts (no time deposits)
    cash_and_deposits: float  # liquid + time deposits, TWD
    monthly_spend: float | None  # average over the last 12 months with data
    monthly_income: float | None  # average over the last 6 months with data
    monthly_net: float | None  # income − spending, same months
    drift: list[tuple[str, float, float, float]] = field(default_factory=list)  # (class, current, target, trade TWD)
    holdings: list[Holding] = field(default_factory=list)
    needs: list[Need] = field(default_factory=list)  # plan spending within near_years
    loan_payment: float | None = None  # highest monthly payment of active plans with a loan
    loan_plans: list[str] = field(default_factory=list)
    deposits: list[Deposit] = field(default_factory=list)


def _item(key: str, level: str, title: str, detail: list[Seg], action: list[Seg] | None = None) -> dict[str, Any]:
    return {"key": key, "level": level, "title": title, "detail": detail, "action": action}


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def check(i: Inputs, thresholds: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Every check that has enough data, warnings first."""
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    out: list[dict[str, Any]] = []

    # 緊急預備金
    if i.monthly_spend and i.monthly_spend > 0:
        months = i.liquid / i.monthly_spend
        lo, hi = t["fund_min_months"], t["fund_max_months"]
        detail: list[Seg] = ["台幣現金與活存 ", m(i.liquid), f"，約 {months:.1f} 個月的支出（每月平均 ", m(i.monthly_spend), "）"]
        if months < lo:
            out.append(_item("fund", "warn", "緊急預備金不足", detail,
                             ["再存 ", m((lo - months) * i.monthly_spend), f" 到 {lo:g} 個月"]))
        elif months > hi:
            out.append(_item("fund", "note", "現金可能太多", detail,
                             [f"超過 {hi:g} 個月的部分約 ", m((months - hi) * i.monthly_spend), "，可考慮投入或轉定存"]))
        else:
            out.append(_item("fund", "ok", "緊急預備金足夠", detail))

    # 配置偏離
    if i.drift:
        off = [(label, cur, tgt, trade) for label, cur, tgt, trade in i.drift if abs(cur - tgt) * 100 > t["drift_pct"]]
        if off:
            label, cur, tgt, trade = max(off, key=lambda r: abs(r[1] - r[2]))
            more = cur > tgt
            if label == "現金":
                action: list[Seg] = ["約 ", m(abs(trade)), " 可以分批投入"] if more else ["保留約 ", m(abs(trade)), " 現金，新的投入先不買"]
            else:
                action = [f"{'賣出' if more else '買進'}約 ", m(abs(trade)), f" 的{label}，或調整之後投入的方向"]
            out.append(_item(
                "drift", "note", "配置偏離目標",
                [f"{label}目前 {_pct(cur)}，目標 {_pct(tgt)}，{'多' if more else '少'} {abs(cur - tgt) * 100:.0f} 個百分點"],
                action,
            ))
        else:
            out.append(_item("drift", "ok", "配置接近目標", [f"每一類都在目標 ±{t['drift_pct']:g} 個百分點內"]))

    # 個股集中
    invested = sum(h.value for h in i.holdings)
    stocks = [h for h in i.holdings if not h.is_fund]
    if invested > 0 and stocks:
        top = max(stocks, key=lambda h: h.value)
        share = top.value / invested
        detail = [f"{top.name} 佔投資 {_pct(share)}（", m(top.value), "）"]
        if share * 100 > t["stock_warn_pct"]:
            out.append(_item("stock", "warn", "單一個股太集中", detail, ["新的資金可以優先放到 ETF 或其他標的"]))
        elif share * 100 > t["stock_note_pct"]:
            out.append(_item("stock", "note", "單一個股比重偏高", detail))
        else:
            out.append(_item("stock", "ok", "個股分散", [f"最大的個股 {top.name} 佔投資 {_pct(share)}"]))

    # 短期資金放在股票
    if i.needs:
        need = sum(n.amount for n in i.needs)
        names = "、".join(f"{n.name}（{n.month[:4]}/{int(n.month[5:])}）" for n in i.needs)
        detail = [f"{t['near_years']:g} 年內的{names}需要 ", m(need), "，現金與定存有 ", m(i.cash_and_deposits)]
        if i.cash_and_deposits < need:
            out.append(_item("near", "warn", "短期要用的錢不夠穩", detail,
                             ["差額 ", m(need - i.cash_and_deposits), " 可以逐步從股票移到現金或定存"]))
        else:
            out.append(_item("near", "ok", "短期資金已備妥", detail))

    # 貸款負擔
    if i.loan_payment and i.monthly_income and i.monthly_income > 0:
        share = i.loan_payment / i.monthly_income
        detail = [f"{'、'.join(i.loan_plans)}的月付最高 ", m(i.loan_payment), f"，佔近 6 個月平均收入 {_pct(share)}"]
        if share * 100 > t["loan_warn_pct"]:
            out.append(_item("loan", "warn", "貸款負擔太重", detail, ["提高頭期款、拉長年期或降低預算"]))
        elif share * 100 > t["loan_note_pct"]:
            out.append(_item("loan", "note", "貸款負擔偏高", detail))
        else:
            out.append(_item("loan", "ok", "貸款負擔可以承受", detail))

    # 儲蓄率
    if i.monthly_income and i.monthly_income > 0 and i.monthly_net is not None:
        rate = i.monthly_net / i.monthly_income
        detail = [f"近 6 個月平均儲蓄率 {_pct(rate)}（每月結餘 ", m(i.monthly_net), "）"]
        if rate * 100 < t["savings_min_pct"]:
            out.append(_item("savings", "note", "儲蓄率偏低", detail, ["到「收支」看哪個分類花最多，設定預算"]))
        else:
            out.append(_item("savings", "ok", "儲蓄率正常", detail))

    # 定存到期
    soon = [d for d in i.deposits if d.days_left <= t["deposit_days"]]
    if soon:
        out.append(_item(
            "deposit", "note", "定存快到期",
            ["、".join(f"{d.name}（{'已到期' if d.days_left <= 0 else f'{d.days_left} 天後'}）" for d in soon)],
            ["到期後記利息收入，再決定轉回或續存"],
        ))

    out.sort(key=lambda a: LEVELS[a["level"]])
    return out
