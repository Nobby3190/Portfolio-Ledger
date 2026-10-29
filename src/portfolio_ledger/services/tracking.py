"""自選股、投資筆記、價格提醒 (DESIGN.md「v1.4」). Gathers what alerts.check needs from the ledger;
the notes are the user's own words, never judged here."""

from __future__ import annotations

import calendar
import json
from collections.abc import Callable, Iterable
from datetime import date as Date
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .. import repo
from ..models import Note, Security
from ..providers import finmind, yahoo
from ..providers.base import ProviderError
from . import alerts, fmt, fundamentals
from .advisor import LEVELS
from .finance import MARKET_LABELS, ZERO, FinanceError, _amount

if TYPE_CHECKING:
    from .ledger import Ledger

THESIS_MAX = 200


def add_months(day: str, months: int) -> str:
    """2026-01-31 + 1 month = 2026-02-28."""
    d = Date.fromisoformat(day[:10])
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return Date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()


def review_due(n: Note) -> str | None:
    if not n.review_months:
        return None
    return add_months(n.last_review or n.created_at[:10], n.review_months)


# ── 投資筆記 ──────────────────────────────────────────────────────────────


def note_view(n: Note | None) -> dict[str, Any] | None:
    if n is None:
        return None
    plain = lambda d: "" if d is None else format(d.normalize(), "f")  # noqa: E731
    return {
        "symbol": n.symbol,
        "thesis": n.thesis,
        "red_lines": n.red_line_list,
        "band_low": fmt.price(n.band_low),
        "band_high": fmt.price(n.band_high),
        "review_months": n.review_months,
        "last_review": n.last_review,
        "review_due": review_due(n),
        "updated_at": n.updated_at[:10],
        "input": {
            "symbol": n.symbol, "thesis": n.thesis, "red_lines": n.red_lines, "band_low": plain(n.band_low),
            "band_high": plain(n.band_high), "review_months": str(n.review_months or ""), "last_review": n.last_review or "",
        },  # fmt: skip
    }


def get_note(lg: Ledger, symbol: str) -> dict[str, Any] | None:
    return note_view(repo.get_note(lg.db, symbol))


def save_note(lg: Ledger, data: dict[str, Any]) -> None:
    symbol = str(data.get("symbol") or "").strip()
    if not symbol:
        raise FinanceError("缺少代號")
    thesis = str(data.get("thesis") or "").strip()
    if len(thesis) > THESIS_MAX:
        raise FinanceError(f"買入理由請寫在 {THESIS_MAX} 字內（現在 {len(thesis)} 字）")
    red = "\n".join(x.strip() for x in str(data.get("red_lines") or "").splitlines() if x.strip())
    low, high = _amount(data.get("band_low"), "合理價下限"), _amount(data.get("band_high"), "合理價上限")
    if low is not None and high is not None and low > high:
        raise FinanceError("合理價下限比上限還高")
    months_s = str(data.get("review_months") or "").strip()
    months = None
    if months_s:
        try:
            months = int(months_s)
        except ValueError:
            raise FinanceError("檢查週期要是整數（月）") from None
        if not 1 <= months <= 60:
            raise FinanceError("檢查週期是 1 到 60 個月")
    last = str(data.get("last_review") or "").strip() or None
    if last:
        try:
            last = Date.fromisoformat(last).isoformat()
        except ValueError:
            raise FinanceError("上次檢查日要是 YYYY-MM-DD") from None
    now = lg.today().isoformat()
    old = repo.get_note(lg.db, symbol)
    if not (thesis or red or low or high or months):
        if old:
            repo.delete_note(lg.db, symbol)  # emptied: nothing left to keep
        return
    repo.save_note(lg.db, Note(symbol, thesis, red, low, high, months, last, old.created_at if old else now, now))


def mark_reviewed(lg: Ledger, symbol: str) -> None:
    n = repo.get_note(lg.db, symbol)
    if n is None:
        raise FinanceError("這檔還沒有投資筆記")
    n.last_review = n.updated_at = lg.today().isoformat()
    repo.save_note(lg.db, n)


# ── 自選股 ────────────────────────────────────────────────────────────────


def week_ago(lg: Ledger, symbol: str, close_date: str | None) -> Decimal | None:
    """The close alerts.WEEK trading days before close_date, from stored prices."""
    if not close_date:
        return None
    start = (Date.fromisoformat(close_date) - timedelta(days=21)).isoformat()
    closes = [c for d, c in repo.closes_from(lg.db, symbol, start) if d <= close_date]
    return closes[-1 - alerts.WEEK] if len(closes) > alerts.WEEK else None


def _band(n: Note | None, close: Decimal | None) -> tuple[str | None, str | None, int]:
    """(band text, where the close sits, -1 below / 0 inside / 1 above)."""
    if n is None or (n.band_low is None and n.band_high is None):
        return None, None, 0
    p = fmt.price
    text = f"{p(n.band_low)}–{p(n.band_high)}" if n.band_low and n.band_high else f"≥ {p(n.band_low)}" if n.band_low else f"≤ {p(n.band_high)}"
    if close is None:
        return text, None, 0
    if n.band_low is not None and close < n.band_low:
        return text, f"低於下限 {abs(close - n.band_low) / n.band_low * 100:.1f}%", -1
    if n.band_high is not None and close > n.band_high:
        return text, f"高於上限 {(close - n.band_high) / n.band_high * 100:.1f}%", 1
    return text, "在區間內", 0


def _row(lg: Ledger, sec: Security, n: Note | None) -> dict[str, Any]:
    week = week_ago(lg, sec.symbol, sec.last_date)
    band, where, side = _band(n, sec.last_close)
    close = sec.last_close
    return {
        "symbol": sec.symbol,
        "name": sec.name,
        "market": MARKET_LABELS.get(sec.market, "海外股"),
        "currency": sec.currency,
        "kind": sec.kind,
        "close": fmt.price(close),
        "close_date": sec.last_date,
        "day_pct": fmt.pct(close - sec.prev_close, sec.prev_close) if close is not None and sec.prev_close else None,
        "day_sign": fmt.sign(close - sec.prev_close) if close is not None and sec.prev_close else 0,
        "week_pct": fmt.pct(close - week, week) if close is not None and week else None,
        "week_sign": fmt.sign(close - week) if close is not None and week else 0,
        "band": band,
        "band_where": where,
        "band_side": side,
        "note": note_view(n),
    }


def watchlist(lg: Ledger) -> list[dict[str, Any]]:
    symbols = repo.list_watchlist(lg.db)
    secs = repo.securities(lg.db, symbols)
    notes = repo.list_notes(lg.db)
    return [_row(lg, secs[s], notes.get(s)) for s in symbols if s in secs]


def add_watch(lg: Ledger, symbol: str) -> str:
    sec = lg.resolve_security(symbol.strip().upper())  # EntryError with a clear message when unknown
    held = {p.symbol for p in lg._replay(repo.list_txs(lg.db)).open_positions()}
    if sec.symbol in held:
        raise FinanceError(f"{sec.name} 已在持股裡")
    repo.add_watch(lg.db, sec.symbol, lg.today().isoformat())
    if not sec.is_tw or week_ago(lg, sec.symbol, sec.last_date) is None:
        lg.backfill_prices([sec])  # so its week change shows right away
    return sec.symbol


def remove_watch(lg: Ledger, symbol: str) -> None:
    repo.remove_watch(lg.db, symbol)


# ── 價格提醒 ──────────────────────────────────────────────────────────────


def alert_settings(lg: Ledger) -> dict[str, Any]:
    try:
        saved = json.loads(repo.get_setting(lg.db, "alerts", "{}"))
    except ValueError:
        saved = {}
    out = dict(alerts.DEFAULTS)
    for k, default in alerts.DEFAULTS.items():
        v = saved.get(k) if isinstance(saved, dict) else None
        if isinstance(default, bool):
            out[k] = bool(v) if v is not None else default
        elif v not in (None, ""):
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                pass
    return out


def save_alert_settings(lg: Ledger, values: dict[str, Any]) -> None:
    out = alert_settings(lg)
    for k in ("day_pct", "week_pct", "fx_pct"):
        if k in values:
            try:
                x = float(str(values[k]).strip())
            except ValueError:
                raise FinanceError("提醒門檻要是數字") from None
            if x <= 0:
                raise FinanceError("提醒門檻要大於 0")
            out[k] = x
    if "card_days" in values:
        s = str(values["card_days"]).strip()
        if not s.isdigit() or int(s) > 28:
            raise FinanceError("卡費提前天數要是 0 到 28 的整數")
        out["card_days"] = int(s)
    for k in ("watchlist", "notify"):
        if k in values:
            out[k] = bool(values[k])
    repo.set_setting(lg.db, "alerts", json.dumps(out))


def card_targets(lg: Ledger, v: dict[str, Any]) -> list[alerts.CardTarget]:
    """The cards paid by 自動扣繳, each with its next bill and the rule's recent postings."""
    today = lg.today()
    since = (today - timedelta(days=alerts.PAID_DAYS - 1)).isoformat()
    balance = {a.id: bal for a, bal, _ in v["accounts"]}
    txs = repo.list_txs(lg.db)
    accounts = repo.list_accounts(lg.db)
    out = []
    for card in accounts:
        if card.type != "credit" or card.statement_day is None or card.pay_day is None:
            continue
        if not (found := lg._autopay_rule(card)):
            continue
        rule, payer_name = found
        payer = next((a for a in accounts if a.name == payer_name), None)
        pay = lg._next_pay_date(card)
        bill = lg._card_due(card, pay, set())
        paid = [(t.date, t.amount) for t in txs
                if t.recurring_id == rule.id and t.account_id == card.id and since <= t.date <= today.isoformat()]  # fmt: skip
        out.append(alerts.CardTarget(
            id=card.id or 0, name=card.name, currency=card.currency, payer=payer_name,
            payer_balance=balance.get(payer.id, ZERO) if payer else ZERO, statement=bill["statement"], pay_date=pay,
            due=bill["due"], paid=paid, rule_id=rule.id or 0, error=rule.error,
        ))  # fmt: skip
    return out


def alerts_report(lg: Ledger) -> dict[str, Any]:
    today = lg.today()
    v = lg._valuation()
    notes = repo.list_notes(lg.db)
    held = {h["symbol"]: h for h in v["open"]}
    watch = [s for s in repo.list_watchlist(lg.db) if s not in held]
    secs = repo.securities(lg.db, [*held, *watch])
    end = (today + timedelta(days=alerts.EXDIV_DAYS)).isoformat()
    exdiv: dict[str, tuple[str, Decimal | None, Decimal | None]] = {}
    for sym, ex, cash, _ in repo.dividend_events(lg.db, held, today.isoformat(), end):
        exdiv.setdefault(sym, (ex, cash, cash * held[sym]["qty"] if cash is not None else None))

    targets = []
    for sym in [*held, *watch]:
        sec = secs.get(sym)
        if sec is None:
            continue
        n = notes.get(sym)
        targets.append(alerts.Target(
            symbol=sym, name=sec.name, held=sym in held, currency=sec.currency, close=sec.last_close,
            close_date=sec.last_date, prev_close=sec.prev_close, week_ago=week_ago(lg, sym, sec.last_date),
            band_low=n.band_low if n else None, band_high=n.band_high if n else None,
            red_lines=n.red_line_list if n else [], review_due=review_due(n) if n else None,
            last_review=n.last_review if n else None, ex_dividend=exdiv.get(sym),
        ))  # fmt: skip
    settings = alert_settings(lg)
    seen = repo.seen_alerts(lg.db)
    found = (alerts.check(targets, today, settings) + alerts.check_cards(card_targets(lg, v), today, settings)
             + alerts.check_fx(fx_targets(lg, secs.values()), settings))  # fmt: skip
    items = sorted((a for a in found if a["key"] not in seen), key=lambda a: LEVELS[a["level"]])
    return {"items": items, "settings": {k: (x if isinstance(x, bool) else f"{x:g}") for k, x in settings.items()}}


def fx_targets(lg: Ledger, secs: Iterable[Security]) -> list[alerts.FxTarget]:
    """The foreign currencies of the open accounts and of the securities held or watched (what
    Ledger.refresh fetches rates for)."""
    currencies = ({a.currency for a in repo.list_accounts(lg.db, True)} | {s.currency for s in secs}) - {"TWD"}
    out = []
    for cur in sorted(currencies):
        rates = repo.fx_last_two(lg.db, cur)
        if rates:
            out.append(alerts.FxTarget(cur, rates[0][1], rates[0][0], rates[1][1] if len(rates) > 1 else None))
    return out


def dismiss_alert(lg: Ledger, key: str) -> None:
    repo.mark_alert_seen(lg.db, key, lg.today().isoformat())


NOTIFY_LISTED = 3


def notify_new(lg: Ledger, send: Callable[[str, str], None]) -> int:
    """One macOS notification for the alerts not sent before (DESIGN.md「系統通知」): titles only, so
    no amount shows on the lock screen. Returns how many it covered."""
    if not alert_settings(lg)["notify"]:
        return 0
    sent = repo.notified_alerts(lg.db)
    new = [a for a in alerts_report(lg)["items"] if a["key"] not in sent]  # warnings first
    if not new:
        return 0
    titles = [a["title"] for a in new]
    if len(new) == 1:
        send("帳本 Ledger", titles[0])
    else:
        body = "、".join(titles[:NOTIFY_LISTED]) + (f"…等 {len(new)} 則" if len(new) > NOTIFY_LISTED else "")
        send(f"帳本 Ledger：{len(new)} 則新提醒", body)
    repo.mark_alerts_notified(lg.db, [a["key"] for a in new], lg.today().isoformat())
    return len(new)


# ── 財報快照 ──────────────────────────────────────────────────────────────

FUND_TTL_DAYS = 7
_UNIT = {"TWD": (Decimal(100_000_000), "億")}
_CASH_UNIT = {"TWD": "元", "USD": "美元", "HKD": "港元", "JPY": "日圓", "CNY": "人民幣", "EUR": "歐元"}


def analysis_commands(sec: Security) -> list[dict[str, str]]:
    """ai-berkshire slash commands to paste into Claude Code (its skills are named in its SKILLS.md)."""
    who = sec.name if sec.is_tw else sec.symbol
    return [
        {"label": "讀最新一期財報", "text": f"/earnings-review {who} 最新"},
        {"label": "買入前檢查", "text": f"/investment-checklist {who}"},
        {"label": "建立或檢查投資論文", "text": f"/thesis-tracker {who}"},
        {"label": "完整研究", "text": f"/investment-research {who}"},
    ]


def fundamentals_report(lg: Ledger, symbol: str, force: bool = False) -> dict[str, Any]:
    sec = repo.get_security(lg.db, symbol)
    if sec is None:
        raise FinanceError(f"找不到代號 {symbol}")
    base = {"symbol": sec.symbol, "name": sec.name}
    if sec.kind in ("etf", "bond_etf"):
        return {**base, "available": False, "reason": "ETF 沒有公司財報"}
    if sec.market not in ("TWSE", "TPEX", "US"):
        return {**base, "available": False, "reason": "港股和其他海外市場的財報之後再支援", "commands": analysis_commands(sec)}

    annual, currency, meta = repo.get_fundamentals(lg.db, sec.symbol)
    today = lg.today()
    fresh = meta is not None and Date.fromisoformat(meta["fetched_at"][:10]) > today - timedelta(days=FUND_TTL_DAYS)
    if force or not fresh:
        source = "FinMind" if sec.is_tw else "Yahoo"
        try:
            if sec.is_tw:
                got, cur = finmind.annual(lg.client, sec.symbol, f"{today.year - 6}-01-01"), "TWD"
            else:
                got, cur = yahoo.fundamentals(lg.client, sec.symbol)
            if not got:
                raise ProviderError("找不到這檔的財報資料")
            repo.put_fundamentals(lg.db, sec.symbol, got, cur, source, today.isoformat())
        except ProviderError as e:
            repo.fundamentals_error(lg.db, sec.symbol, str(e), today.isoformat(), source)
        annual, currency, meta = repo.get_fundamentals(lg.db, sec.symbol)

    currency = currency or sec.currency
    unit, unit_name = _UNIT.get(currency, (Decimal(1_000_000), "百萬"))
    valuation = None
    if sec.pe is not None or sec.pb is not None or sec.dividend_yield is not None:
        valuation = {
            "pe": f"{sec.pe:.2f}" if sec.pe is not None else None,
            "pb": f"{sec.pb:.2f}" if sec.pb is not None else None,
            "dividend_yield": f"{sec.dividend_yield:.2f}%" if sec.dividend_yield is not None else None,
        }
    return {
        **base,
        "available": True,
        "currency": currency,
        "unit": f"{fmt.CURRENCY_NAMES.get(currency, currency)}{unit_name}",
        "table": fundamentals.table(annual, unit) if annual else None,
        "checks": fundamentals.checks(annual, unit, f"{fmt.CURRENCY_NAMES.get(currency, currency)}{unit_name}") if annual else [],
        "valuation": valuation,
        "source": meta["source"] if meta else None,
        "fetched_at": meta["fetched_at"][:10] if meta else None,
        "error": meta["error"] if meta else None,
        "commands": analysis_commands(sec),
    }


# ── 匯出持倉給 ai-berkshire ───────────────────────────────────────────────


def holdings_line(lg: Ledger) -> str:
    """One /portfolio-review line: 台積電 1000股 @580元, 騰訊 0700.HK 200股 @480港元, 現金 15%."""
    v = lg._valuation()
    parts = []
    for h in sorted(v["open"], key=lambda h: h["value_twd"], reverse=True):
        who = h["name"] if h["market"] in ("TWSE", "TPEX") else f"{h['name']} {h['symbol']}"
        cur = h["cost_currency"]
        # No thousands separators: the list itself is comma-separated.
        qty = format(h["qty"].normalize(), "f")
        cost = format((h["cost"] / h["qty"]).quantize(Decimal("0.01")).normalize(), "f")
        parts.append(f"{who} {qty}股 @{cost}{_CASH_UNIT.get(cur, cur)}")
    cash = sum((x for x in v["cash_twd"].values() if x > 0), Decimal(0))
    invested = sum((h["value_twd"] for h in v["open"]), Decimal(0))
    if cash + invested > 0:
        parts.append(f"現金 {cash / (cash + invested) * 100:.0f}%")
    return "/portfolio-review " + ", ".join(parts)


def holdings_markdown(lg: Ledger) -> str:
    st = lg.state()
    lines = [
        f"# 持倉 {lg.today().isoformat()}",
        "",
        "由帳本 Ledger 匯出。在 Claude Code 的 ai-berkshire 資料夾貼上下面這行：",
        "",
        "```",
        holdings_line(lg),
        "```",
        "",
        "| 代號 | 名稱 | 股數 | 平均成本 | 市值（台幣） | 佔總資產 | 未實現損益（台幣） |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for h in st["holdings"]:
        lines.append(
            f"| {h['symbol']} | {h['name']} | {h['qty']} | {h['avg_cost']} {h['cost_currency']} | {h['value_twd']} |"
            f" {h['weight'] * 100:.1f}% | {h['unrealized']} |"
        )
    lines += ["", f"總資產 NT$ {st['total']}；投資總報酬 {st['total_return']}（{st['total_return_pct'] or '—'}）"]
    return "\n".join(lines) + "\n"
