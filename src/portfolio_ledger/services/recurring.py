"""週期性收支: rules that post a one-line command on each due date, up to today.

Posting goes through Ledger.commit, so a rule behaves exactly like typing its line on that day.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date as Date
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from .. import repo
from ..models import RECURRING_FREQS, Recurring
from . import fmt
from .quick import ParseError, format_command, parse

if TYPE_CHECKING:
    from .ledger import Ledger

ACTIONS = ("income", "expense", "transfer", "repay", "dca")
# One occurrence as a share of a month, for the panel's monthly totals.
PER_MONTH = {"monthly": Decimal(1), "weekly": Decimal(52) / 12, "yearly": Decimal(1) / 12}
log = logging.getLogger(__name__)


def nth(start: Date, freq: str, k: int) -> Date:
    """The k-th occurrence (0 = start). Days past a month's end fall on its last day (31st → 30th, Feb 29 → 28)."""
    if freq == "weekly":
        return start + timedelta(weeks=k)
    months = k * (12 if freq == "yearly" else 1)
    y, m = divmod(start.month - 1 + months, 12)
    y += start.year
    return Date(y, m + 1, min(start.day, calendar.monthrange(y, m + 1)[1]))


def due_dates(rule: Recurring, until: Date) -> list[str]:
    """Occurrences after rule.last_date, up to `until` and the rule's end date."""
    start = Date.fromisoformat(rule.start_date)
    end = min(until, Date.fromisoformat(rule.end_date)) if rule.end_date else until
    after = rule.last_date or ""
    out: list[str] = []
    k = 0
    while (d := nth(start, rule.freq, k)) <= end:
        if d.isoformat() > after:
            out.append(d.isoformat())
        k += 1
    return out


def next_date(rule: Recurring) -> str | None:
    """The first occurrence after last_date (None once past the end date)."""
    start = Date.fromisoformat(rule.start_date)
    after = rule.last_date or ""
    k = 0
    while (d := nth(start, rule.freq, k)).isoformat() <= after:
        k += 1
    if rule.end_date and d.isoformat() > rule.end_date:
        return None
    return d.isoformat()


def dated(line: str, day: str) -> str:
    """The rule's line with a date, put before the # note."""
    body, sep, note = line.partition("#")
    return f"{body.strip()} {day}" + (f" #{note}" if sep else "")


def run_due(lg: Ledger) -> int:
    """Post everything due up to today; a failing rule stops at that date and keeps the error. Returns how many."""
    from .ledger import EntryError, NothingDue, QuoteNotYet

    today = lg.today()
    posted = 0
    with lg._lock:
        for rule in repo.list_recurring(lg.db):
            if not rule.active:
                continue
            changed = False
            start = Date.fromisoformat(rule.start_date)
            for day in due_dates(rule, today):
                k = next(k for k in range(100000) if nth(start, rule.freq, k).isoformat() >= day)
                until = nth(start, rule.freq, k + 1).isoformat()
                if repo.has_recurring_tx(lg.db, rule.id or 0, day, until):
                    pass  # already posted (the app stopped before saving last_date)
                else:
                    try:
                        if not lg.adopt(dated(rule.line, day), rule.id or 0):
                            lg.commit(dated(rule.line, day), recurring_id=rule.id)
                            posted += 1
                    except QuoteNotYet:
                        break  # 定額 before the close: try again after the next quote refresh
                    except NothingDue:
                        pass  # 還 @卡: this bill is already paid
                    except EntryError as e:
                        log.warning("recurring %s on %s: %s", rule.id, day, e)
                        rule.error = f"{day}：{e}"
                        changed = True
                        break
                rule.last_date, rule.error, changed = day, None, True
                repo.save_recurring(lg.db, rule)  # after each posting, so a crash never posts twice
            if changed:
                repo.save_recurring(lg.db, rule)
    return posted


def _plain_line(lg: Ledger, line: str) -> str:
    """Validate a rule's line and return it normalized (no date)."""
    from .ledger import EntryError

    try:
        cmd = parse(line, lg.today())
    except ParseError as e:
        raise EntryError(str(e) or "要填一行內容，例如：支出 15000 居住 @台新 # 房租") from e
    if cmd.action not in ACTIONS:
        raise EntryError("週期性只能是 支出、收入、轉、還、定額")
    if cmd.date:
        raise EntryError("一行內容不要寫日期，日期由起始日和頻率決定")
    if cmd.missing:
        raise EntryError("還缺金額")
    preview = lg.preview(line)
    if preview["status"] != "ready" and not preview.get("settled"):
        raise EntryError(preview.get("message") or "這一行記不進去")
    return format_command(
        cmd.action, symbol=cmd.symbol, amount=cmd.amount, account=cmd.account, to_account=cmd.to_account,
        category=cmd.category, fee=cmd.fee, fx=cmd.fx, interest=cmd.interest, note=cmd.note,
    )  # fmt: skip


def _rule_from(lg: Ledger, data: dict[str, Any]) -> Recurring:
    from .ledger import EntryError, _optional_date

    line = _plain_line(lg, str(data.get("line") or ""))
    freq = data.get("freq") or "monthly"
    if freq not in RECURRING_FREQS:
        raise EntryError("頻率不正確")
    start = _optional_date(data.get("start_date"), "起始日") or lg.today().isoformat()
    end = _optional_date(data.get("end_date"), "結束日")
    if end and end < start:
        raise EntryError("結束日要在起始日之後")
    rule = Recurring(None, line, freq, start, end, active=bool(data.get("active", True)))
    if data.get("id") is not None:
        old = repo.get_recurring(lg.db, int(data["id"]))
        if old is None:
            raise EntryError("找不到這條規則")
        rule.id, rule.sort = old.id, old.sort
        # Moving the start keeps what was posted; only dates after the last posting are added.
        rule.last_date = old.last_date
        if rule.active and not old.active:  # resuming: skip what fell due while paused
            yesterday = (lg.today() - timedelta(days=1)).isoformat()
            rule.last_date = max(old.last_date or "", yesterday)
    _check_backfill_overlap(lg, rule)
    return rule


def _symbol(line: str, today: Date) -> str | None:
    """The stock a 定額 rule buys (None for other rules)."""
    from .ledger import normalize_symbol

    cmd = parse(line, today)
    return normalize_symbol(cmd.symbol) if cmd.action == "dca" and cmd.symbol else None


def dca_rules(lg: Ledger) -> dict[int, tuple[str, Recurring]]:
    """定額 rules by id, with the symbol each buys."""
    today = lg.today()
    return {r.id: (sym, r) for r in repo.list_recurring(lg.db) if r.id is not None and (sym := _symbol(r.line, today))}


def _check_backfill_overlap(lg: Ledger, rule: Recurring) -> None:
    """A 定額 must not post on or before a 補登 of the same stock: that 補登 already holds those shares."""
    from .ledger import EntryError

    sym = _symbol(rule.line, lg.today())
    if sym is None or not rule.active:
        return
    backfilled = max((t.date for t in repo.list_txs(lg.db) if t.kind == "holding_in" and t.symbol == sym), default=None)
    due = due_dates(rule, lg.today())
    if backfilled and due and due[0] <= backfilled:
        raise EntryError(
            f"{sym} 在 {backfilled} 有補登持股，已經包含之前定期定額的股數。起始日請設在 {backfilled} 之後，或先修改補登。"
        )


def backfill_count(lg: Ledger, data: dict[str, Any]) -> int:
    """How many entries saving `data` would post right away (shown before saving)."""
    from .ledger import EntryError

    try:
        rule = _rule_from(lg, data)
    except EntryError:
        return 0
    return len(due_dates(rule, lg.today()))


def save(lg: Ledger, data: dict[str, Any]) -> int:
    """Create or update a rule, then post what is due. Returns how many entries were posted."""
    rule = _rule_from(lg, data)
    rule.error = None
    repo.save_recurring(lg.db, rule)
    return run_due(lg)


def start_dca(lg: Ledger, text: str, freq: str = "monthly") -> int:
    """記一筆的定期定額＋每月重複: a rule from the line's date, posted now if that close is out, else after it.
    Returns how many entries were posted."""
    cmd = parse(text, lg.today())
    return save(lg, {"line": _undated(lg, text), "freq": freq, "start_date": cmd.date or lg.today().isoformat()})


def from_commit(lg: Ledger, text: str, tx_id: int, freq: str = "monthly") -> None:
    """記一筆的「每月重複」: a rule for the line just saved, starting on its date (already posted)."""
    tx = repo.get_tx(lg.db, tx_id)
    if tx is None:
        return
    rule_id = repo.save_recurring(
        lg.db, Recurring(None, _plain_line(lg, _undated(lg, text)), freq, tx.date, last_date=tx.date)
    )
    repo.mark_recurring(lg.db, tx_id, rule_id)


def _undated(lg: Ledger, text: str) -> str:
    cmd = parse(text, lg.today())
    return format_command(
        cmd.action, symbol=cmd.symbol, amount=cmd.amount, account=cmd.account, to_account=cmd.to_account,
        category=cmd.category, fee=cmd.fee, fx=cmd.fx, interest=cmd.interest, note=cmd.note,
    )  # fmt: skip


def delete(lg: Ledger, rule_id: int) -> None:
    repo.delete_recurring(lg.db, rule_id)


def _figure(s: str | None) -> Decimal | None:
    """The number in a formatted amount ("−15,000" → 15000)."""
    digits = "".join(c for c in s or "" if c.isdigit() or c == ".")
    try:
        return Decimal(digits) if digits else None
    except InvalidOperation:
        return None


def rows(lg: Ledger) -> list[dict[str, Any]]:
    """The rules for the 週期性收支 panel."""
    out = []
    for r in repo.list_recurring(lg.db):
        p = lg.preview(r.line)
        cmd = parse(r.line, lg.today())
        bill = p.get("card") or p.get("settled")  # 還 @卡 without an amount: the bill changes every month
        amount = p.get("total") if p["status"] == "ready" else (fmt.money(cmd.amount) if cmd.amount else None)
        each = _figure(amount)
        if bill and cmd.amount is None:
            amount, each = "帳單金額", None
        category = cmd.category or {"expense": "其他", "income": "其他收入"}.get(cmd.action)
        # No note: an income/expense rule is called by its category (薪資), others by the preview title.
        named = category if cmd.action in ("income", "expense") and cmd.category else None
        title = cmd.note or named or (p.get("title") if p["status"] == "ready" else None) or r.line
        out.append(
            {
                "id": r.id,
                "line": r.line,
                "title": title,
                "kind": cmd.action,
                "category": category,
                "amount": amount,
                # This rule's amount per month (weekly ×52÷12, yearly ÷12); paused rules count nothing.
                "monthly": float(each * PER_MONTH[r.freq]) if each and r.active else None,
                "freq": r.freq,
                "freq_label": RECURRING_FREQS[r.freq],
                "start_date": r.start_date,
                "end_date": r.end_date,
                "last_date": r.last_date,
                "next_date": next_date(r) if r.active else None,
                "active": r.active,
                "error": r.error,
            }
        )
    return out
