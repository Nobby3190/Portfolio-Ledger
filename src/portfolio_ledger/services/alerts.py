"""提醒: rules on the stored closes and the user's own 投資筆記 (DESIGN.md「v1.4」), on the bills of
cards paid by 自動扣繳 (DESIGN.md「信用卡自動扣繳」), and on the daily FX moves of the currencies held
(DESIGN.md「價格提醒」). Pure functions.

Each alert has a key that names the rule, the symbol and the day it is about, so 「知道了」 hides it
until the same condition shows up on a new day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date
from decimal import Decimal
from typing import Any

from . import fmt
from .advisor import LEVELS, Seg

DEFAULTS = {"day_pct": 5.0, "week_pct": 10.0, "watchlist": True, "card_days": 3, "fx_pct": 1.0, "notify": True}
WEEK = 5  # trading days
EXDIV_DAYS = 7
PAID_DAYS = 7  # how long 已自動扣繳 stays


@dataclass
class Target:
    symbol: str
    name: str
    held: bool  # False: on the watchlist
    currency: str
    close: Decimal | None
    close_date: str | None
    prev_close: Decimal | None
    week_ago: Decimal | None  # close WEEK trading days before close_date
    band_low: Decimal | None = None
    band_high: Decimal | None = None
    red_lines: list[str] = field(default_factory=list)
    review_due: str | None = None  # when the next 檢查 is due
    last_review: str | None = None
    ex_dividend: tuple[str, Decimal | None, Decimal | None] | None = None  # (date, per share, estimate) within EXDIV_DAYS


@dataclass
class CardTarget:
    """A card with an autopay rule, and its next bill: the one paid on the first 扣款日 after today."""

    id: int
    name: str
    currency: str
    payer: str
    payer_balance: Decimal
    statement: str  # that bill's 結帳日
    pay_date: str
    due: Decimal  # owed on the 結帳日 less what was paid in since
    paid: list[tuple[str, Decimal]] = field(default_factory=list)  # the rule's postings in the last PAID_DAYS
    rule_id: int = 0
    error: str | None = None  # the rule's: 「2026-10-20：…」


@dataclass
class FxTarget:
    """A currency held (an account or a security in it), with its last two market mid-rates."""

    currency: str
    rate: Decimal
    date: str
    prev_rate: Decimal | None


def _change(now: Decimal, before: Decimal | None) -> Decimal | None:
    return (now - before) / before if before else None


def _pct(x: Decimal) -> str:
    return f"{abs(x) * 100:.1f}%"


def _md(d: str) -> str:
    return f"{int(d[5:7])}/{int(d[8:])}"


def _item(key: str, level: str, t: Target, title: str, detail: list[Seg], action: list[Seg] | None = None,
          red: bool = False, kind: str = "dismiss") -> dict[str, Any]:  # fmt: skip
    return {
        "key": key, "level": level, "symbol": t.symbol, "name": t.name, "held": t.held, "title": title,
        "detail": detail, "action": action, "red_lines": t.red_lines if red else [], "kind": kind,
    }  # fmt: skip


def check(targets: list[Target], today: Date, settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    s = {**DEFAULTS, **(settings or {})}
    day_pct, week_pct = Decimal(str(s["day_pct"])), Decimal(str(s["week_pct"]))
    out: list[dict[str, Any]] = []
    for t in targets:
        if not t.held and not s["watchlist"]:
            continue
        p = fmt.price
        why = ["回去看你當初為什麼買"] if t.held and t.red_lines else None
        if t.close is not None and t.close_date:
            # 單日異動
            day = _change(t.close, t.prev_close)
            if day is not None and abs(day) * 100 >= day_pct:
                out.append(_item(
                    f"day:{t.symbol}:{t.close_date}", "note", t, f"{t.name} {'漲' if day > 0 else '跌'} {_pct(day)}",
                    [f"{_md(t.close_date)} 收 {p(t.close)}（前一日 {p(t.prev_close)}）"], why, red=True,
                ))  # fmt: skip
            # 一週異動
            week = _change(t.close, t.week_ago)
            if week is not None and abs(week) * 100 >= week_pct:
                out.append(_item(
                    f"week:{t.symbol}:{t.close_date}", "warn", t, f"{t.name} 一週{'漲' if week > 0 else '跌'} {_pct(week)}",
                    [f"{WEEK} 個交易日從 {p(t.week_ago)} 到 {p(t.close)}"], why, red=True,
                ))  # fmt: skip
            # 合理價區間
            if t.band_low is not None and t.close < t.band_low:
                out.append(_item(
                    f"low:{t.symbol}:{t.close_date}", "note", t, f"{t.name} 低於合理價下限",
                    [f"收 {p(t.close)}，低於你設的下限 {p(t.band_low)}"],
                    ["照筆記重新確認買入理由還成立嗎"] if t.held else ["是否照計劃買進，先看筆記裡的理由和紅線"],
                ))  # fmt: skip
            if t.band_high is not None and t.close > t.band_high:
                out.append(_item(
                    f"high:{t.symbol}:{t.close_date}", "note", t, f"{t.name} 高於合理價上限",
                    [f"收 {p(t.close)}，高於你設的上限 {p(t.band_high)}"],
                    ["看筆記決定要不要調整區間或部位"] if t.held else None,
                ))  # fmt: skip
        # 該檢查了: stays until 「標記為已檢查」
        if t.review_due and t.review_due <= today.isoformat():
            since = f"上次檢查 {t.last_review.replace('-', '/')}" if t.last_review else "還沒檢查過"
            out.append(_item(
                f"review:{t.symbol}:{t.review_due}", "note", t, f"{t.name} 該檢查投資筆記了",
                [f"{since}，到期日 {t.review_due.replace('-', '/')}"], ["逐條看紅線有沒有發生，看完按「標記為已檢查」"],
                red=True, kind="review",
            ))  # fmt: skip
        # 即將除息 (held only)
        if t.held and t.ex_dividend:
            ex, cash, est = t.ex_dividend
            detail: list[Seg] = [f"{_md(ex)} 除息"]
            if cash is not None:
                detail.append(f"，每股 {p(cash)}")
            if est is not None:
                detail += ["，預估 ", {"m": fmt.money(est, t.currency) or "0"}]
            out.append(_item(f"exdiv:{t.symbol}:{ex}", "ok", t, f"{t.name} 即將除息", detail))
    out.sort(key=lambda a: LEVELS[a["level"]])
    return out


def _card_item(key: str, level: str, c: CardTarget, title: str, detail: list[Seg],
               action: list[Seg] | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "key": key, "level": level, "symbol": "", "name": c.name, "held": True, "title": title,
        "detail": detail, "action": action, "red_lines": [], "kind": "dismiss",
    }  # fmt: skip


def check_cards(cards: list[CardTarget], today: Date, settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """出帳 → 扣款預告 (or 餘額不夠) → 已自動扣繳, and 扣款失敗 while the rule keeps an error."""
    days = int((settings or {}).get("card_days", DEFAULTS["card_days"]))
    out: list[dict[str, Any]] = []
    for c in cards:
        m = lambda d: {"m": fmt.money(d, c.currency) or "0"}  # noqa: E731
        # the bill closed and is still owed: 出帳 until the 預告 takes over
        if c.statement < today.isoformat() and c.due > 0:
            if (Date.fromisoformat(c.pay_date) - today).days > days:
                out.append(_card_item(
                    f"bill:{c.id}:{c.statement}", "note", c, f"{c.name} 已出帳",
                    [f"{_md(c.statement)} 結帳，帳單 ", m(c.due), f"，{_md(c.pay_date)} 從{c.payer}自動扣"],
                ))  # fmt: skip
            elif c.payer_balance < c.due:
                out.append(_card_item(
                    f"short:{c.id}:{c.pay_date}", "warn", c, f"{c.payer}餘額不夠繳{c.name}卡費",
                    [f"{_md(c.pay_date)} 要扣 ", m(c.due), f"，{c.payer}現在 ", m(c.payer_balance)],
                    ["先轉 ", m(c.due - c.payer_balance), f" 到{c.payer}"],
                ))  # fmt: skip
            else:
                out.append(_card_item(
                    f"due:{c.id}:{c.pay_date}", "note", c, f"{c.name}卡費 {_md(c.pay_date)} 自動扣款",
                    ["帳單 ", m(c.due), f"，從{c.payer}扣"],
                ))  # fmt: skip
        for day, amount in c.paid:
            out.append(_card_item(f"paid:{c.id}:{day}", "ok", c, f"已自動扣繳{c.name}卡費",
                                  [f"{_md(day)} 從{c.payer}扣 ", m(amount)]))  # fmt: skip
        if c.error:
            day, _, why = c.error.partition("：")  # run_due writes 「date：why」
            out.append(_card_item(f"fail:{c.rule_id}:{day}", "warn", c, f"{c.name}卡費自動扣繳失敗",
                                  [f"{_md(day)} {why}"], ["到週期性收支看這條規則"]))  # fmt: skip
    return out


def check_fx(targets: list[FxTarget], settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """匯率異動: a held currency moved fx_pct or more against TWD since the day before."""
    pct = Decimal(str((settings or {}).get("fx_pct", DEFAULTS["fx_pct"])))
    out: list[dict[str, Any]] = []
    for t in targets:
        move = _change(t.rate, t.prev_rate)
        if move is None or abs(move) * 100 < pct:
            continue
        name = fmt.CURRENCY_NAMES.get(t.currency, t.currency)
        out.append({
            "key": f"fx:{t.currency}:{t.date}", "level": "note", "symbol": "", "name": name, "held": True,
            "title": f"{name} {'漲' if move > 0 else '跌'} {_pct(move)}",
            "detail": [f"{_md(t.date)} 1 {name} = {t.rate:.4f} 台幣（前一日 {t.prev_rate:.4f}）"],
            "action": [f"外幣部位的台幣價值跟著{'增加' if move > 0 else '減少'}"], "red_lines": [], "kind": "dismiss",
        })  # fmt: skip
    return out
