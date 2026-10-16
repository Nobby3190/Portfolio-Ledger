"""價格提醒: rules on the stored closes and the user's own 投資筆記. Pure functions (DESIGN.md「v1.4」).

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

DEFAULTS = {"day_pct": 5.0, "week_pct": 10.0, "watchlist": True}
WEEK = 5  # trading days
EXDIV_DAYS = 7


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
