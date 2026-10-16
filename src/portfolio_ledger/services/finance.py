"""收支 (monthly income/expense, budgets), 規劃 (life plans, goals, rebalancing, FIRE, DCA backtest) and 健檢."""

from __future__ import annotations

import calendar
import json
import unicodedata
from datetime import UTC, datetime
from datetime import date as Date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .. import repo
from ..models import GOAL_SCOPES, LIFE_PLAN_KINDS, Goal, LifePlan, Tx
from ..providers import yahoo
from ..providers.base import ProviderError
from . import advisor, dividends, fmt, planner

if TYPE_CHECKING:
    from .ledger import Ledger

ZERO = Decimal(0)
DEFAULT_TARGETS = {"股票": 70, "債券": 20, "現金": 10}
DEFAULT_PLAN = {"current": "", "monthly": "", "return": "6", "inflation": "2", "spend": "", "withdrawal": "4"}


class FinanceError(ValueError):
    pass


shift_month = planner.shift_month


def _twd(t: Tx) -> Decimal:
    return abs(t.amount) * (t.fx_rate if t.fx_rate is not None else Decimal(1))


def _flows(txs: list[Tx]) -> dict[str, dict[str, dict[int | None, Decimal]]]:
    """month -> kind (income/expense) -> category id -> TWD."""
    out: dict[str, dict[str, dict[int | None, Decimal]]] = {}
    for t in txs:
        if t.kind not in ("income", "expense"):
            continue
        cats = out.setdefault(t.date[:7], {"income": {}, "expense": {}})[t.kind]
        cats[t.category_id] = cats.get(t.category_id, ZERO) + _twd(t)
    return out


def _sum(flows: dict, month: str, kind: str) -> Decimal:
    return sum(flows.get(month, {}).get(kind, {}).values(), ZERO)


# ── 收支 ────────────────────────────────────────────────────────────────


def month_report(lg: Ledger, month: str | None = None) -> dict[str, Any]:
    today = lg.today()
    this_month = today.isoformat()[:7]
    month = month or this_month
    if len(month) != 7 or month[4] != "-":
        raise FinanceError("月份格式要是 YYYY-MM")
    # Future months can be opened (to look ahead and set budgets) up to December, or next month in December.
    latest = max(f"{today.year}-12", shift_month(this_month, 1))
    if month > latest:
        raise FinanceError(f"最遠只能看到 {latest[:4]} 年 {int(latest[5:])} 月")
    future = month > this_month
    flows = _flows(repo.list_txs(lg.db))
    income, expense = _sum(flows, month, "income"), _sum(flows, month, "expense")
    net = income - expense
    prev = shift_month(month, -1)

    cats = repo.list_categories(lg.db)
    spent = flows.get(month, {}).get("expense", {})
    last = flows.get(prev, {}).get("expense", {})
    rows = []
    for c in cats:
        if c.kind != "expense":
            continue
        s, l = spent.get(c.id, ZERO), last.get(c.id, ZERO)
        if c.archived and not s:
            continue
        rows.append(
            {
                "id": c.id,
                "name": c.name,
                "spent": fmt.money(s),
                "budget": fmt.money(c.budget) if c.budget else None,
                "budget_raw": f"{c.budget.normalize():f}" if c.budget else "",
                "budget_ratio": float(s / c.budget) if c.budget else None,
                "share": float(s / expense) if expense else 0.0,
                "last": fmt.money(l) if l else None,
                "delta": fmt.money(s - l, signed=True) if l or s else None,
                "delta_sign": fmt.sign(s - l),
                "raw": s,
            }
        )
    rows.sort(key=lambda r: (-r["raw"], r["name"]))
    for r in rows:
        r.pop("raw")
    income_rows = [
        {"name": c.name, "amount": fmt.money(flows.get(month, {}).get("income", {}).get(c.id, ZERO))}
        for c in cats
        if c.kind == "income" and flows.get(month, {}).get("income", {}).get(c.id)
    ]

    total_setting = repo.get_setting(lg.db, "budget_total", "")
    budget = Decimal(total_setting) if total_setting else sum((c.budget for c in cats if c.budget), ZERO) or None
    days_left = None
    if future:
        pass  # nothing spent yet; the whole budget is left
    elif month == this_month:
        days_left = calendar.monthrange(today.year, today.month)[1] - today.day + 1
    left = budget - expense if budget else None

    def point(m: str) -> dict[str, Any]:
        inc, exp = _sum(flows, m, "income"), _sum(flows, m, "expense")
        return {"month": m, "label": f"{int(m[5:])} 月", "income": float(inc), "expense": float(exp),
                "income_s": fmt.money(inc), "expense_s": fmt.money(exp), "future": m > this_month}  # fmt: skip

    # The chart never runs into the future; the tabs add the months still to come this year.
    anchor = min(month, this_month)
    trend = [point(shift_month(anchor, -i)) for i in range(5, -1, -1)]
    tabs = list(trend)
    if anchor == this_month:
        m = shift_month(this_month, 1)
        while m <= latest:
            tabs.append(point(m))
            m = shift_month(m, 1)

    return {
        "month": month,
        "label": f"{month[:4]} 年 {int(month[5:])} 月",
        "prev": prev,
        "next": shift_month(month, 1) if month < latest else None,
        "is_current": month == this_month,
        "is_future": future,
        "income": fmt.money(income),
        "expense": fmt.money(expense),
        "net": fmt.money(net, signed=True),
        "net_sign": fmt.sign(net),
        "savings_rate": fmt.pct(net, income) if income else None,
        "budget": fmt.money(budget) if budget else None,
        "budget_total_setting": total_setting,
        "budget_ratio": float(expense / budget) if budget else None,
        "budget_left": fmt.money(left) if left is not None else None,
        "over": left is not None and left < 0,
        "days_left": days_left,
        "per_day": fmt.money(left / days_left) if left is not None and left > 0 and days_left else None,
        "categories": rows,
        "income_categories": income_rows,
        "trend": trend,
        "tabs": tabs,
        "has_data": bool(income or expense),
    }


def year_report(lg: Ledger, year: str | int | None = None) -> dict[str, Any]:
    """The 收支 view's 年 mode: a year's totals against last year, its months, categories and net worth."""
    today = lg.today()
    try:
        y = int(year) if year else today.year
    except ValueError:
        raise FinanceError("年份要是數字") from None
    if not 1900 <= y <= today.year:
        raise FinanceError(f"只能看到 {today.year} 年")
    flows = _flows(repo.list_txs(lg.db))
    this_month = today.isoformat()[:7]

    elapsed = today.month if y == today.year else 12  # months the averages are over

    def months(yy: int, upto: int = 12) -> list[str]:
        return [f"{yy:04d}-{m:02d}" for m in range(1, upto + 1)]

    def total(yy: int, kind: str, upto: int = 12) -> Decimal:
        return sum((_sum(flows, m, kind) for m in months(yy, upto)), ZERO)

    def by_cat(yy: int, kind: str, upto: int = 12) -> dict[int | None, Decimal]:
        out: dict[int | None, Decimal] = {}
        for m in months(yy, upto):
            for cid, x in flows.get(m, {}).get(kind, {}).items():
                out[cid] = out.get(cid, ZERO) + x
        return out

    # This year is compared with the same months of last year (Jan–Oct against Jan–Oct).
    income, expense = total(y, "income"), total(y, "expense")
    last_income, last_expense = total(y - 1, "income", elapsed), total(y - 1, "expense", elapsed)
    net, last_net = income - expense, last_income - last_expense

    def change(now: Decimal, before: Decimal) -> dict[str, Any] | None:
        if not before:
            return None
        return {"delta": fmt.money(now - before, signed=True), "pct": fmt.pct(now - before, before), "sign": fmt.sign(now - before)}

    spent, before = by_cat(y, "expense"), by_cat(y - 1, "expense", elapsed)
    rows = []
    for c in repo.list_categories(lg.db, "expense"):
        x, l = spent.get(c.id, ZERO), before.get(c.id, ZERO)
        if not x and not l:
            continue
        budget = c.budget * 12 if c.budget else None
        rows.append(
            {
                "id": c.id, "name": c.name, "amount": fmt.money(x), "share": float(x / expense) if expense else 0.0,
                "per_month": fmt.money(x / elapsed), "last": fmt.money(l) if l else None,
                "delta": fmt.money(x - l, signed=True) if l else None, "delta_sign": fmt.sign(x - l),
                "budget": fmt.money(budget) if budget else None, "budget_ratio": float(x / budget) if budget else None,
                "raw": x,
            }
        )  # fmt: skip
    rows.sort(key=lambda r: (-r["raw"], r["name"]))
    for r in rows:
        r.pop("raw")
    earned = by_cat(y, "income")
    income_rows = [
        {"name": c.name, "amount": fmt.money(earned[c.id]), "share": float(earned[c.id] / income) if income else 0.0}
        for c in repo.list_categories(lg.db, "income")
        if earned.get(c.id)
    ]

    trend = []
    for m in months(y):
        inc, exp = _sum(flows, m, "income"), _sum(flows, m, "expense")
        trend.append({"month": m, "label": f"{int(m[5:])} 月", "income": float(inc), "expense": float(exp),
                      "income_s": fmt.money(inc), "expense_s": fmt.money(exp), "future": m > this_month})  # fmt: skip

    snaps = repo.list_snapshots(lg.db)
    first_day, last_day = f"{y}-01-01", f"{y}-12-31"
    start = next((x for d, x in reversed(snaps) if d < first_day), None)
    if start is None:
        start = next((x for d, x in snaps if first_day <= d <= last_day), None)
    end = next((x for d, x in reversed(snaps) if d <= last_day), None)
    worth = None
    if start is not None and end is not None:
        worth = {"start": fmt.money(start), "end": fmt.money(end), "change": fmt.money(end - start, signed=True),
                 "pct": fmt.pct(end - start, start) if start > 0 else None, "sign": fmt.sign(end - start)}  # fmt: skip

    years = sorted({int(m[:4]) for m in flows} | {today.year})
    return {
        "year": y,
        "label": f"{y} 年",
        "is_current": y == today.year,
        "elapsed": elapsed,
        "income": fmt.money(income),
        "expense": fmt.money(expense),
        "net": fmt.money(net, signed=True),
        "net_sign": fmt.sign(net),
        "savings_rate": fmt.pct(net, income) if income else None,
        "per_month": fmt.money(expense / elapsed),
        "compare_label": f"比 {y - 1} 年" if elapsed == 12 else f"比 {y - 1} 年 1–{elapsed} 月",
        "vs_last": {
            "income": change(income, last_income),
            "expense": change(expense, last_expense),
            "net": change(net, last_net) if last_net else None,
            "savings_rate": fmt.pct(last_net, last_income) if last_income else None,
        },
        "categories": rows,
        "income_categories": income_rows,
        "trend": trend,
        "worth": worth,
        "tabs": [{"year": yy, "label": f"{yy}", "expense": fmt.money(total(yy, "expense"))} for yy in years],
        "has_data": bool(income or expense),
    }


def set_budget(lg: Ledger, category_id: int, amount: str) -> None:
    if repo.get_category(lg.db, category_id) is None:
        raise FinanceError("找不到這個分類")
    repo.set_category_budget(lg.db, category_id, _amount(amount, "預算"))


def set_total_budget(lg: Ledger, amount: str) -> None:
    d = _amount(amount, "總預算")
    repo.set_setting(lg.db, "budget_total", str(d) if d is not None else "")


def _amount(v: object, label: str) -> Decimal | None:
    # Full-width digits from the 注音 IME, thousands commas, 元/%, and a trailing 萬 (30萬 = 300,000).
    s = unicodedata.normalize("NFKC", str(v or "")).replace(",", "").replace(" ", "").rstrip("元%")
    if not s:
        return None
    scale = Decimal(1)
    if s.endswith("萬"):
        s, scale = s[:-1], Decimal(10000)
    try:
        d = Decimal(s) * scale
    except Exception:
        raise FinanceError(f"{label}要是數字") from None
    if not d.is_finite() or d < 0:
        raise FinanceError(f"{label}不能是負數")
    return d or None


# ── 規劃 ────────────────────────────────────────────────────────────────


def _averages(lg: Ledger) -> dict[str, Any]:
    """Monthly averages over the months that have data: net savings and income over the last 6,
    spending over the last 12."""
    flows = _flows(repo.list_txs(lg.db))
    this_month = lg.today().isoformat()[:7]
    months6 = [m for m in (shift_month(this_month, -i) for i in range(6)) if m in flows]
    months12 = [m for m in (shift_month(this_month, -i) for i in range(12)) if m in flows]
    income6 = [_sum(flows, m, "income") for m in months6]
    nets = [_sum(flows, m, "income") - _sum(flows, m, "expense") for m in months6]
    spend12 = sum((_sum(flows, m, "expense") for m in months12), ZERO)
    return {
        "net": sum(nets, ZERO) / len(nets) if nets else None,
        "income": sum(income6, ZERO) / len(income6) if income6 else None,
        "spend": spend12 / len(months12) if months12 else None,
        "months12": len(months12),
    }


def _recent_averages(lg: Ledger) -> tuple[Decimal, Decimal, int]:
    """(average monthly net savings over the last 6 months with data, annual spending, months used)."""
    a = _averages(lg)
    return a["net"] or ZERO, (a["spend"] or ZERO) * 12, a["months12"]


def _goal_current(v: dict[str, Any], scope: str, ids: list[int]) -> Decimal:
    """What a savings goal has so far, by its 追蹤範圍."""
    if scope == "total":
        return v["total"]
    if scope == "accounts":
        return sum((v["acc_value_twd"].get(i, ZERO) for i in ids), ZERO)
    # cash / cash_deposit: TWD bank and cash balances plus the TWD cash in broker accounts (never the stocks).
    out = ZERO
    for a, bal, _ in v["accounts"]:
        if a.archived or a.currency != "TWD":
            continue
        if a.type in ("bank", "cash", "broker_tw", "broker_us"):
            out += bal
        elif a.type == "deposit" and scope == "cash_deposit":
            out += v["acc_value_twd"].get(a.id or 0, ZERO)
    return out


def plan(lg: Ledger) -> dict[str, Any]:
    v = lg._valuation()
    total: Decimal = v["total"]
    today = lg.today()
    accounts = {a.id: a for a, _, _ in v["accounts"]}

    goals = []
    for g in repo.list_goals(lg.db):
        ids = [i for i in g.account_ids or [] if i in accounts]
        current = _goal_current(v, g.scope, ids)
        left = g.target - current
        months = planner.months_between(today, Date.fromisoformat(g.deadline)) if g.deadline else None
        goals.append(
            {
                "id": g.id,
                "name": g.name,
                "target": fmt.money(g.target),
                "target_raw": f"{g.target.normalize():f}",
                "deadline": g.deadline,
                "account_ids": ids,
                "accounts": [accounts[i].name for i in ids],
                "scope": g.scope,
                "scope_label": GOAL_SCOPES.get(g.scope, g.scope),
                "current": fmt.money(current),
                "ratio": float(current / g.target) if g.target else 0.0,
                "left": fmt.money(left) if left > 0 else None,
                "done": left <= 0,
                "months_left": months,
                "per_month": fmt.money(left / months) if left > 0 and months else None,
                "overdue": bool(g.deadline and g.deadline < today.isoformat() and left > 0),
            }
        )

    targets = _targets(lg)
    classes = {k: float(x) for k, x in v["classes"].items()}
    rebalance = [
        {
            "label": r.label,
            "value": fmt.money(Decimal(str(round(r.value)))),
            "current": r.current,
            "target": r.target,
            "target_raw": targets.get(r.label, 0),
            "trade": fmt.money(Decimal(str(round(r.trade))), signed=True),
            "trade_sign": 1 if r.trade > 0.5 else -1 if r.trade < -0.5 else 0,
            "off": round((r.current - r.target) * 100, 1),
        }
        for r in planner.rebalance(classes, targets)
    ]

    income = _averages(lg)["income"]
    # Plans without their own accounts share what the others have not claimed, earliest first,
    # so nothing is counted twice.
    rows = repo.list_life_plans(lg.db)
    claimed = {i for p in rows for i in p.account_ids or [] if i in accounts}
    pool = [total - sum((v["acc_value_twd"].get(i, ZERO) for i in claimed), ZERO)]
    plans = [_life_plan(lg, p, v, pool, income) for p in rows]
    return {
        "goals": goals,
        "rebalance": rebalance,
        "life_plans": [p for p, _ in plans],
        "fire": _fire(lg, total, [(p["name"], e) for p, e in plans if e is not None]),
    }


# ── 人生計劃 ──────────────────────────────────────────────────────────────


def _loan(p: LifePlan) -> tuple[float, planner.Loan | None]:
    """(down payment, loan) in today's money. No down ratio = paid in full; a loan needs rate and term."""
    price = float(p.price)
    if p.down_ratio is None:
        return price, None
    down = price * float(p.down_ratio) / 100
    principal = price - down
    if principal <= 0 or p.loan_rate is None or not p.loan_years:
        return down, None
    return down, planner.amortize(principal, float(p.loan_rate) / 100, float(p.loan_years), float(p.grace_years or 0))


def _plan_month(lg: Ledger, p: LifePlan) -> int | None:
    """Months from today to the plan's month (at least 1), or None without a month."""
    if not p.target_month:
        return None
    return max(1, planner.months_between(lg.today(), Date.fromisoformat(p.target_month + "-01")) + 1)


def _life_plan(
    lg: Ledger, p: LifePlan, v: dict[str, Any], pool: list[Decimal], income: Decimal | None
) -> tuple[dict[str, Any], planner.PlanEvent | None]:
    """The row for the 人生計劃 card, and its event for the projection (active plans with a month).

    pool: [net worth not yet set aside for an earlier plan]; plans without accounts draw from it.
    """
    down, loan = _loan(p)
    need = down + float(p.one_off or 0)
    ids = [i for i in p.account_ids or [] if i in v["acc_by_id"]]
    if ids:
        saved = float(sum((v["acc_value_twd"].get(i, ZERO) for i in ids), ZERO))
    else:
        saved = max(0.0, min(float(pool[0]), need))
        pool[0] -= Decimal(str(saved))
    left = need - saved
    months = None
    if p.target_month:
        first = Date.fromisoformat(p.target_month + "-01")
        months = planner.months_between(lg.today(), first) if first > lg.today() else 0
    extra = float(p.monthly_cost or 0) - float(p.rent_saved or 0)
    top_payment = max(loan.grace_payment, loan.payment) if loan else None
    burden = top_payment / float(income) if top_payment and income and income > 0 else None
    t = _advice_thresholds(lg)
    level = None
    if burden is not None:
        level = "warn" if burden * 100 > t["loan_warn_pct"] else "note" if burden * 100 > t["loan_note_pct"] else "ok"

    def money(x: float | None, signed: bool = False) -> str | None:
        return None if x is None else fmt.money(Decimal(round(x)), signed=signed)

    def raw(d: Decimal | None) -> str:
        return "" if d is None else f"{d.normalize():f}"

    row = {
        "id": p.id,
        "kind": p.kind,
        "kind_label": LIFE_PLAN_KINDS.get(p.kind, p.kind),
        "name": p.name,
        "target_month": p.target_month,
        "active": p.active,
        "price": money(float(p.price)),
        "need": money(need),
        "down": money(down),
        "one_off": money(float(p.one_off)) if p.one_off else None,
        "saved": money(min(saved, need)),
        "ratio": min(1.0, saved / need) if need > 0 else 1.0,
        "left": money(left) if left > 0 else None,
        "months_left": months,
        "per_month": money(left / months) if left > 0 and months else None,
        "loan": None
        if loan is None
        else {
            "principal": money(float(p.price) - down),
            "payment": money(loan.payment),
            "grace_payment": money(loan.grace_payment) if loan.grace_months else None,
            "grace_months": loan.grace_months,
            "years": raw(p.loan_years),
            "total_interest": money(loan.total_interest),
        },
        "extra_monthly": money(extra, signed=True) if extra else None,
        "burden": burden,
        "burden_level": level,
        "account_ids": ids,
        "accounts": [v["acc_by_id"][i].name for i in ids],
        "input": {
            "id": p.id, "kind": p.kind, "name": p.name, "target_month": p.target_month or "",
            "price": raw(p.price), "down_ratio": raw(p.down_ratio), "one_off": raw(p.one_off),
            "loan_rate": raw(p.loan_rate), "loan_years": raw(p.loan_years), "grace_years": raw(p.grace_years),
            "monthly_cost": raw(p.monthly_cost), "rent_saved": raw(p.rent_saved), "account_ids": ids,
            "active": p.active,
        },
    }  # fmt: skip
    month = _plan_month(lg, p)
    event = planner.PlanEvent(month, need, loan, extra) if p.active and month is not None else None
    return row, event


def save_life_plan(lg: Ledger, data: dict[str, Any]) -> int:
    # The user names the plan; the kind is no longer chosen (2026-10-13), new plans are "other".
    kind = str(data.get("kind") or "other")
    if kind not in LIFE_PLAN_KINDS:
        raise FinanceError("請選擇計劃類型")
    name = str(data.get("name", "")).strip()
    if not name:
        raise FinanceError("計劃要有名稱")
    price = _amount(data.get("price"), "價格")
    if not price:
        raise FinanceError("價格要大於 0")
    month = str(data.get("target_month") or "").strip() or None
    if month:
        try:
            month = Date.fromisoformat(month[:7] + "-01").isoformat()[:7]
        except ValueError:
            raise FinanceError("目標年月要是 YYYY-MM 格式") from None
    down = _amount(data.get("down_ratio"), "頭期款比例")
    if down is None and str(data.get("down_ratio") or "").strip():
        down = ZERO  # "0" means a full loan, not "paid in full"
    if down is not None and down > 100:
        raise FinanceError("頭期款比例不能超過 100%")
    years = _amount(data.get("loan_years"), "貸款年期")
    grace = _amount(data.get("grace_years"), "寬限期")
    if grace and years and grace >= years:
        raise FinanceError("寬限期要比貸款年期短")
    rate = _amount(data.get("loan_rate"), "貸款利率")
    if rate is None and str(data.get("loan_rate") or "").strip():
        rate = ZERO
    pid = data.get("id")
    plan = LifePlan(
        int(pid) if pid is not None else None, kind, name, price, month, down,
        _amount(data.get("one_off"), "一次性費用"), rate, years, grace,
        _amount(data.get("monthly_cost"), "每月持有成本"), _amount(data.get("rent_saved"), "省下的房租"),
        [int(i) for i in data.get("account_ids") or []], bool(data.get("active", True)),
    )  # fmt: skip
    return repo.save_life_plan(lg.db, plan)


def delete_life_plan(lg: Ledger, plan_id: int) -> None:
    repo.delete_life_plan(lg.db, plan_id)


# ── 健檢 ──────────────────────────────────────────────────────────────────


def _advice_thresholds(lg: Ledger) -> dict[str, float]:
    try:
        saved = json.loads(repo.get_setting(lg.db, "advice", "{}"))
    except ValueError:
        saved = {}
    out = dict(advisor.DEFAULT_THRESHOLDS)
    for k in out:
        try:
            if saved.get(k) not in (None, ""):
                out[k] = float(saved[k])
        except (TypeError, ValueError, AttributeError):
            pass
    return out


def save_advice_thresholds(lg: Ledger, values: dict[str, Any]) -> None:
    out = {}
    for k in advisor.DEFAULT_THRESHOLDS:
        s = str(values.get(k, "") or "").strip()
        if not s:
            continue
        try:
            x = float(s)
        except ValueError:
            raise FinanceError("健檢門檻要是數字") from None
        if x < 0:
            raise FinanceError("健檢門檻不能是負數")
        out[k] = x
    repo.set_setting(lg.db, "advice", json.dumps(out))


def advice(lg: Ledger) -> dict[str, Any]:
    v = lg._valuation()
    t = _advice_thresholds(lg)
    avg = _averages(lg)
    liquid = deposits = ZERO
    for a, bal, _ in v["accounts"]:
        if a.archived:
            continue
        if a.type in ("bank", "cash") and a.currency == "TWD":
            liquid += bal
        elif a.type == "deposit":
            deposits += v["acc_value_twd"].get(a.id or 0, ZERO)

    total: Decimal = v["total"]
    holdings = [
        advisor.Holding(h["name"], float(h["value_twd"]), h["kind"] in ("etf", "bond_etf"), MARKET_LABELS.get(h["market"], "海外股"))
        for h in v["open"]
    ]
    foreign = sum((h["value_twd"] for h in v["open"] if h["currency"] != "TWD"), ZERO)
    for a, bal, _ in v["accounts"]:
        if not a.archived and a.currency != "TWD" and bal > 0:
            foreign += bal * (v["rate"](a.currency) or ZERO)
    brokers: dict[str, Decimal] = {}
    for acc_id, value in v["acc_hold_twd"].items():
        acc = v["acc_by_id"][acc_id]
        name = acc.group_name or acc.name  # a multi-currency account is one broker
        brokers[name] = brokers.get(name, ZERO) + value
    drift = []
    if holdings:
        classes = {k: float(x) for k, x in v["classes"].items()}
        drift = [(r.label, r.current, r.target, r.trade) for r in planner.rebalance(classes, _targets(lg))]

    needs, loans, loan_names = [], [], []
    horizon = round(t["near_years"] * 12)
    for p in repo.list_life_plans(lg.db):
        if not p.active:
            continue
        down, loan = _loan(p)
        month = _plan_month(lg, p)
        if month is not None and month <= horizon:
            needs.append(advisor.Need(p.name, p.target_month or "", down + float(p.one_off or 0)))
        if loan:
            loans.append(max(loan.grace_payment, loan.payment))
            loan_names.append(p.name)
    for name, pay in lg.loan_payments():  # loans already running
        loans.append(float(pay))
        loan_names.append(name)

    inputs = advisor.Inputs(
        liquid=float(liquid),
        cash_and_deposits=float(liquid + deposits),
        monthly_spend=float(avg["spend"]) if avg["spend"] else None,
        monthly_income=float(avg["income"]) if avg["income"] else None,
        monthly_net=float(avg["net"]) if avg["net"] is not None else None,
        drift=drift,
        holdings=holdings,
        needs=needs,
        loan_payment=sum(loans) if loans else None,
        loan_plans=loan_names,
        deposits=[advisor.Deposit(d["name"], d["days_left"]) for d in lg._deposits(v) if d["days_left"] is not None],
        total=float(total),
        foreign=float(foreign),
        brokers=[(k, float(x)) for k, x in brokers.items()],
    )
    items = advisor.check(inputs, t) if total > 0 else []
    return {"items": items, "thresholds": {k: f"{x:g}" for k, x in t.items()}}


MARKET_LABELS = {"TWSE": "台股", "TPEX": "台股", "US": "美股", "HK": "港股"}


# ── 股利 ──────────────────────────────────────────────────────────────────

UPCOMING_DAYS = 60


def dividend_report(lg: Ledger) -> dict[str, Any]:
    """The 股利 card: last 12 months, yield on cost, share of spending, coming 除息 (DESIGN.md v1.4)."""
    v = lg._valuation()
    today = lg.today()
    paid = lg._paid_dividends(v)
    avg = _averages(lg)
    annual = avg["spend"] * 12 if avg["spend"] else None
    s = dividends.summarize(paid, {h["symbol"]: h["cost_twd"] for h in v["open"]}, annual, today)
    names = {h["symbol"]: h["name"] for h in v["holdings"].values()}

    held = {h["symbol"]: h for h in v["open"]}
    end = Date.fromordinal(today.toordinal() + UPCOMING_DAYS).isoformat()
    upcoming = []
    for sym, ex, cash, pay in repo.dividend_events(lg.db, held, today.isoformat(), end):
        h = held[sym]
        upcoming.append({
            "symbol": sym, "name": h["name"], "ex_date": ex, "pay_date": pay,
            "cash": fmt.price(cash) if cash is not None else None, "currency": h["currency"],
            "estimate": fmt.money(cash * h["qty"], h["currency"]) if cash is not None else None,
        })  # fmt: skip

    return {
        "has": bool(paid) or bool(upcoming),
        "ttm": fmt.money(s.ttm),
        "ytd": fmt.money(s.ytd),
        "yield_on_cost": fmt.pct(s.yield_on_cost, Decimal(1)) if s.yield_on_cost is not None else None,
        "cover": fmt.pct(s.cover, Decimal(1)) if s.cover is not None else None,
        "by_symbol": [
            {"symbol": k, "name": names.get(k, k), "amount": fmt.money(x), "ratio": float(x / s.ttm) if s.ttm else 0.0,
             "held": k in held}
            for k, x in s.by_symbol
        ],  # fmt: skip
        "upcoming": upcoming,
    }


def _targets(lg: Ledger) -> dict[str, float]:
    try:
        raw = json.loads(repo.get_setting(lg.db, "targets", ""))
        return {k: float(raw.get(k, 0)) for k in DEFAULT_TARGETS}
    except (ValueError, AttributeError):
        return {k: float(x) for k, x in DEFAULT_TARGETS.items()}


def save_targets(lg: Ledger, values: dict[str, Any]) -> None:
    out = {}
    for k in DEFAULT_TARGETS:
        try:
            x = float(str(values.get(k, 0) or 0))
        except ValueError:
            raise FinanceError(f"{k}的比例要是數字") from None
        if x < 0:
            raise FinanceError(f"{k}的比例不能是負數")
        out[k] = x
    if sum(out.values()) <= 0:
        raise FinanceError("目標比例加起來要大於 0")
    repo.set_setting(lg.db, "targets", json.dumps(out))


def _plan_params(lg: Ledger) -> dict[str, str]:
    try:
        saved = json.loads(repo.get_setting(lg.db, "plan", "{}"))
    except ValueError:
        saved = {}
    return {k: str(saved.get(k, d)) for k, d in DEFAULT_PLAN.items()}


def save_plan(lg: Ledger, values: dict[str, Any]) -> None:
    params = _plan_params(lg)
    for k in DEFAULT_PLAN:
        if k in values:
            s = str(values[k] or "").replace(",", "").strip()
            if s:
                try:
                    float(s)
                except ValueError:
                    raise FinanceError("試算的欄位要是數字") from None
            params[k] = s
    repo.set_setting(lg.db, "plan", json.dumps(params))


def _fire(lg: Ledger, total: Decimal, events: list[tuple[str, planner.PlanEvent]] | None = None) -> dict[str, Any]:
    params = _plan_params(lg)
    monthly_auto, spend_auto, months_of_data = _recent_averages(lg)
    auto = {"current": float(total), "monthly": float(monthly_auto), "spend": float(spend_auto)}

    def val(k: str, default: float) -> float:
        return float(params[k]) if params[k] != "" else default

    current = val("current", auto["current"])
    monthly = val("monthly", auto["monthly"])
    spend = val("spend", auto["spend"])
    ret, infl, wd = val("return", 6), val("inflation", 2), val("withdrawal", 4)
    if spend <= 0:
        return {"params": params, "auto": _auto_strings(auto), "months_of_data": months_of_data, "ready": False}
    r = planner.fire(current, monthly, ret / 100, infl / 100, spend, wd / 100)
    reach = r.months_to_target
    today = lg.today()

    def year_of(months: int | None) -> int | None:
        return None if months is None else today.year + (months + today.month - 1) // 12

    with_plans = None
    if events:
        p = planner.fire(current, monthly, ret / 100, infl / 100, spend, wd / 100, events=[e for _, e in events])
        delay = None if p.months_to_target is None or reach is None else round((p.months_to_target - reach) / 12, 1)
        with_plans = {
            "names": [n for n, _ in events],
            "target": fmt.money(Decimal(str(round(p.target)))),
            "target_raw": p.target,
            "years": None if p.months_to_target is None else round(p.months_to_target / 12, 1),
            "year": year_of(p.months_to_target),
            "delay_years": delay,
            "series": [{"year": y, "value": round(x)} for y, x in p.series],
            "marks": [{"name": n, "year": e.month / 12} for n, e in events],
        }
    return {
        "params": params,
        "auto": _auto_strings(auto),
        "months_of_data": months_of_data,
        "ready": True,
        "target": fmt.money(Decimal(str(round(r.target)))),
        "target_raw": r.target,
        "reached_now": reach == 0,
        "years": None if reach is None else round(reach / 12, 1),
        "year": year_of(reach),
        "series": [{"year": y, "value": round(x)} for y, x in r.series],
        "progress": min(1.0, current / r.target) if r.target else 0.0,
        "with_plans": with_plans,
    }


def _auto_strings(auto: dict[str, float]) -> dict[str, str]:
    return {k: str(round(x)) for k, x in auto.items()}


def save_goal(lg: Ledger, data: dict[str, Any]) -> int:
    name = str(data.get("name", "")).strip()
    if not name:
        raise FinanceError("目標要有名稱")
    target = _amount(data.get("target"), "目標金額")
    if not target:
        raise FinanceError("目標金額要大於 0")
    deadline = str(data.get("deadline") or "").strip() or None
    if deadline:
        try:
            deadline = Date.fromisoformat(deadline).isoformat()
        except ValueError:
            raise FinanceError("期限要是 YYYY-MM-DD 格式") from None
    ids = [int(i) for i in data.get("account_ids") or []]
    # Callers that send no scope (older ones) meant: ticked accounts, else the whole net worth.
    scope = str(data.get("scope") or ("accounts" if ids else "total"))
    if scope not in GOAL_SCOPES:
        raise FinanceError("請選擇追蹤範圍")
    if scope == "accounts" and not ids:
        raise FinanceError("自訂帳戶要勾選至少一個帳戶")
    gid = data.get("id")
    return repo.save_goal(
        lg.db, Goal(int(gid) if gid is not None else None, name, target, deadline, ids if scope == "accounts" else [], scope=scope)
    )


def delete_goal(lg: Ledger, goal_id: int) -> None:
    repo.delete_goal(lg.db, goal_id)


def backtest(lg: Ledger, symbol: str, start: str, amount: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if not symbol:
        raise FinanceError("請輸入代號")
    amt = _amount(amount, "每月金額")
    if not amt:
        raise FinanceError("每月金額要大於 0")
    try:
        begin = datetime.strptime(start.strip()[:7], "%Y-%m").replace(tzinfo=UTC)
    except ValueError:
        raise FinanceError("開始月份要是 YYYY-MM") from None
    if begin.date() > lg.today():
        raise FinanceError("開始月份不能在未來")
    try:
        sec = lg.resolve_security(symbol)
    except ValueError as e:
        raise FinanceError(str(e)) from e
    ysym = f"{symbol}.TW" if sec.market == "TWSE" else f"{symbol}.TWO" if sec.market == "TPEX" else symbol
    try:
        prices = yahoo.monthly(lg.client, ysym, begin)
    except ProviderError as e:
        raise FinanceError(str(e)) from e
    if not prices:
        raise FinanceError(f"{symbol} 在這段期間沒有價格資料")
    bt = planner.dca([(d, float(p)) for d, p in prices], float(amt), lg.today())
    gain = bt.value - bt.invested
    cur = sec.currency
    return {
        "symbol": symbol,
        "name": sec.name,
        "currency": cur,
        "from": prices[0][0][:7],
        "months": len(bt.series),
        "invested": fmt.money(Decimal(str(bt.invested)), cur),
        "value": fmt.money(Decimal(str(round(bt.value, 2))), cur),
        "gain": fmt.money(Decimal(str(round(gain, 2))), cur, signed=True),
        "gain_sign": 1 if gain > 0 else -1 if gain < 0 else 0,
        "return_pct": fmt.pct(Decimal(str(gain)), Decimal(str(bt.invested))),
        # Annualising a few months of returns gives silly numbers; only show it from a year on.
        "xirr": None if bt.xirr is None or len(bt.series) < 12 else f"{bt.xirr * 100:+.2f}%".replace("-", "−"),
        "series": [{"month": m, "invested": round(i, 2), "value": round(x, 2)} for m, i, x in bt.series],
    }
