"""The app's use cases: preview/commit a command line, build the page state, refresh quotes.

api.py is a thin wrapper around this; poller.py calls refresh(). Thread-safety comes from Db's lock
plus self._lock around the multi-step operations.
"""

from __future__ import annotations

import calendar
import csv
import logging
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .. import repo
from ..db import Db
from ..models import ACCOUNT_TYPES, RECURRING_FREQS, SPENDING_TYPES, TX_KINDS, Account, Category, Recurring, Security, Tx
from ..providers import cathay, finmind, twse, yahoo
from ..providers.base import ProviderError, make_client
from . import dividends, fees, fmt, planner, recurring
from .portfolio import Book, PortfolioError, replay
from .quick import CATEGORY_KINDS, FIELD_NAMES, Command, ParseError, format_command, parse

TAIPEI = ZoneInfo("Asia/Taipei")
TW_CODE = re.compile(r"^\d{4,6}[A-Z]?$")
HK_CODE = re.compile(r"^(\d{1,5})\.HK$")
FOREIGN_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")


def normalize_symbol(symbol: str) -> str:
    """700.HK / 00700.HK -> 0700.HK (Yahoo's four-digit form); everything else unchanged."""
    if m := HK_CODE.match(symbol):
        return f"{int(m.group(1)):04d}.HK"
    return symbol


def market_of(symbol: str) -> str:
    """Market for a non-Taiwan Yahoo symbol: HK for .HK, US without a suffix, INTL otherwise."""
    if symbol.endswith(".HK"):
        return "HK"
    return "US" if "." not in symbol else "INTL"
COMPOSER_KINDS = ("expense", "income", "transfer", "buy", "sell", "cash_dividend")
GUESS_DAYS = 365  # auto-category looks this far back
LOAN_INTEREST = "貸款利息"
BROKER_TYPES = ("broker_tw", "broker_us")
ZERO = Decimal(0)
MAX_GROUPS = 6
HOLDINGS_KEY = "_holdings"  # snapshot breakdown: holdings market value, for the 持股市值 chart
INVEST_LABELS = ("台股", "美股", "港股", "海外股", "債券")  # the investment classes of _asset_classes
log = logging.getLogger(__name__)


class EntryError(ValueError):
    pass


DCA_NOTE = "定期定額"  # a 定額 buy priced at the close (an estimate of the broker's fill)
DCA_CONFIRMED = "定期定額（已對帳）"


class NothingDue(EntryError):
    """還 @卡 without an amount when the bill is already paid; a recurring rule just moves on."""


class QuoteNotYet(EntryError):
    """定額: the close it buys at is not published yet; a recurring rule waits instead of failing."""

    def __init__(self, message: str, day: str) -> None:
        super().__init__(message)
        self.day = day


def taipei_now() -> datetime:
    return datetime.now(TAIPEI)


@dataclass
class Draft:
    txs: list[Tx]  # one row, or both legs of a transfer
    account: Account
    security: Security | None = None
    to_account: Account | None = None
    category: str | None = None  # display name for income/expense
    new_category: str | None = None  # created on commit
    guessed: bool = False  # category taken from past entries with the same note
    repay: dict[str, Decimal] | None = None  # 還: principal, interest, owed (before)
    bill: dict[str, Any] | None = None  # 還 @卡 without an amount: statement date, owed, paid since, due
    dca: Decimal | None = None  # 定額: the fixed amount the buy was sized from

    @property
    def tx(self) -> Tx:
        return self.txs[0]


class Ledger:
    def __init__(
        self,
        db: Db,
        client: httpx.Client | None = None,
        today: Callable[[], Date] = lambda: taipei_now().date(),
    ) -> None:
        self.db = db
        self.client = client or make_client()
        self.client_is_mock = client is not None  # tests inject a client; the real app uses per-site clients
        self.today = today
        self._lock = threading.RLock()
        self._us_misses: dict[str, str] = {}  # symbols Yahoo didn't know, so typing doesn't refetch them
        self.status: dict[str, Any] = {"refreshed_at": None, "errors": [], "running": False}
        self._filled: set[tuple[str, str]] = set()  # 定額 gaps already fetched from Yahoo
        self._convert_openings()

    # ── settings ────────────────────────────────────────────────────────

    def settings(self) -> dict[str, str]:
        return {
            "fee_discount": repo.get_setting(self.db, "fee_discount", str(fees.DEFAULT_DISCOUNT)),
            "fee_min": repo.get_setting(self.db, "fee_min", str(fees.DEFAULT_MIN_FEE)),
            # 隱藏金額: '1' = open with the amounts hidden; showing them takes Touch ID or the login password.
            # A new key (2026-10-18): the old 'privacy' was the on/off state itself and is no longer read.
            "privacy_lock": repo.get_setting(self.db, "privacy_lock", "1"),
            "up_color": repo.get_setting(self.db, "up_color", "red"),  # Taiwan: red is up
            # Foreign cash valuation: 'cathay' = 國泰世華 即期買進 (like the 國泰 app), 'market' = Yahoo mid-rate.
            "fx_source": repo.get_setting(self.db, "fx_source", "market"),
        }

    def save_settings(self, values: dict[str, str]) -> None:
        for key in ("fee_discount", "fee_min"):
            if key in values:
                d = _positive(values[key], "手續費折扣" if key == "fee_discount" else "最低手續費", allow_zero=True)
                repo.set_setting(self.db, key, str(d))
        for key, allowed in (("privacy_lock", {"0", "1"}), ("up_color", {"red", "green"}), ("fx_source", {"cathay", "market"})):
            if key in values:
                if values[key] not in allowed:
                    raise EntryError(f"{key} 的值不正確")
                repo.set_setting(self.db, key, values[key])

    def _fee_terms(self, a: Account) -> tuple[Decimal, Decimal]:
        s = self.settings()
        return (
            a.fee_discount if a.fee_discount is not None else Decimal(s["fee_discount"]),
            a.fee_min if a.fee_min is not None else Decimal(s["fee_min"]),
        )

    # ── accounts ────────────────────────────────────────────────────────

    @staticmethod
    def _valid_name(raw: object) -> str:
        name = str(raw or "").strip()
        if not name:
            raise EntryError("帳戶要有名稱")
        if any(ch.isspace() for ch in name) or "@" in name or "#" in name:
            raise EntryError("帳戶名稱不能有空白、@ 或 #（一行輸入要用 @名稱 指定帳戶）")
        return name

    @staticmethod
    def _valid_color(raw: object) -> str | None:
        color = str(raw or "").strip().lower()
        if not color:
            return None
        if not re.fullmatch(r"#[0-9a-f]{6}", color):
            raise EntryError("顏色要是 #rrggbb")
        return color

    def _renamed_rules(self, renames: dict[int, str], group: tuple[str, str] | None = None) -> list[Recurring]:
        """Recurring rules rewritten for accounts about to be renamed ({account id: new name}; group: (old, new)
        multi-currency name). Resolved against the current names, so call it before saving the rename."""
        out = []
        for r in repo.list_recurring(self.db):
            head, sep, note = r.line.partition("#")
            words = head.split()
            changed = False
            for i, w in enumerate(words):
                if not w.startswith("@"):
                    continue
                name = w[1:]
                if group and name.lower() == group[0].lower():
                    new = group[1]
                else:
                    try:
                        acc = self._pick_account(Command("expense"), None, name)
                    except EntryError:
                        continue
                    new = renames.get(acc.id or 0)
                if new and new != name:
                    words[i], changed = f"@{new}", True
            if changed:
                r.line = " ".join(words) + (f" #{note}" if sep else "")
                out.append(r)
        return out

    def save_group(self, data: dict[str, Any]) -> None:
        """Create or update a multi-currency account: one part per currency, named "{name}-{CUR}".

        Removing a currency deletes its part, or archives it when it already has transactions.
        """
        name = self._valid_name(data.get("name"))
        old = str(data.get("old_name") or "").strip() or None
        type_ = data.get("type") or "bank"
        if type_ not in ("bank", "cash", "broker_us"):
            raise EntryError("多幣別帳戶只能是銀行、現金或複委託")
        color = self._valid_color(data.get("color"))
        currencies = sorted({str(c).upper() for c in data.get("currencies") or []})
        if not currencies:
            raise EntryError("至少要選一種幣別")
        if any(not re.fullmatch(r"[A-Z]{3}", c) for c in currencies):
            raise EntryError("幣別要是三個英文字母")
        everything = repo.list_accounts(self.db, True)
        parts = [a for a in everything if a.group_name == (old or name)]
        if old is None and parts:
            raise EntryError(f"已經有叫「{name}」的帳戶")
        taken = {a.name for a in everything if a not in parts} | {a.group_name for a in everything if a.group_name and a not in parts}
        if name in taken or any(f"{name}-{c}" in taken for c in currencies):
            raise EntryError(f"已經有叫「{name}」的帳戶")
        by_cur = {a.currency: a for a in parts}
        rules = self._renamed_rules({a.id or 0: f"{name}-{a.currency}" for a in parts}, (old, name) if old else None)
        for a in parts:  # rename / restore / retire existing parts
            a.name, a.group_name, a.type, a.color = f"{name}-{a.currency}", name, type_, color
            if a.currency in currencies:
                a.archived = False
                repo.save_account(self.db, a)
            elif repo.account_tx_count(self.db, a.id or 0):
                a.archived = True
                repo.save_account(self.db, a)
            else:
                repo.save_account(self.db, a)
                repo.delete_account(self.db, a.id or 0)
        for c in currencies:
            if c not in by_cur:
                repo.save_account(self.db, Account(None, f"{name}-{c}", type_, c, group_name=name, color=color))
        for r in rules:  # rules naming the old @帳戶 keep working
            repo.save_recurring(self.db, r)

    def delete_group(self, name: str) -> None:
        parts = [a for a in repo.list_accounts(self.db, True) if a.group_name == name]
        if any(repo.account_tx_count(self.db, a.id or 0) for a in parts):
            raise EntryError("帳戶裡還有交易，不能刪除（可以把幣別取消勾選來封存）")
        for a in parts:
            repo.delete_account(self.db, a.id or 0)

    def save_account(self, data: dict[str, Any]) -> int:
        name = self._valid_name(data.get("name"))
        type_ = data.get("type")
        if type_ not in ACCOUNT_TYPES:
            raise EntryError("帳戶類型不正確")
        currency = str(data.get("currency") or ("USD" if type_ == "broker_us" else "TWD")).upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise EntryError("幣別要是三個英文字母，例如 TWD、USD")
        acc_id = data.get("id")
        if acc_id is not None:
            old = repo.get_account(self.db, int(acc_id))
            if old is None:
                raise EntryError("找不到這個帳戶")
            if old.currency != currency and repo.account_tx_count(self.db, old.id or 0):
                raise EntryError("帳戶已經有交易，不能改幣別")
        everything = repo.list_accounts(self.db, True)
        clash = [a for a in everything if a.name == name and a.id != acc_id] or [a for a in everything if a.group_name == name]
        if clash:
            raise EntryError(f"已經有叫「{name}」的帳戶")
        acc = Account(
            id=int(acc_id) if acc_id is not None else None,
            name=name,
            type=type_,
            currency=currency,
            fee_discount=_optional_positive(data.get("fee_discount"), "手續費折扣"),
            fee_min=_optional_positive(data.get("fee_min"), "最低手續費"),
            archived=bool(data.get("archived", False)),
            sort=int(data.get("sort", 0)),
            group_name=old.group_name if acc_id is not None and old is not None else None,
            color=self._valid_color(data.get("color")),
        )
        if type_ == "deposit":
            acc.rate = _optional_positive(data.get("rate"), "年利率")
            acc.start_date = _optional_date(data.get("start_date"), "起存日")
            acc.maturity_date = _optional_date(data.get("maturity_date"), "到期日")
            if acc.start_date and acc.maturity_date and acc.maturity_date <= acc.start_date:
                raise EntryError("到期日要在起存日之後")
        elif type_ == "loan":
            acc.principal = _optional_positive(data.get("principal"), "貸款金額")
            acc.rate = _optional_positive(data.get("rate"), "年利率")
            acc.term_years = _optional_positive(data.get("term_years"), "年期")
            acc.grace_years = _optional_positive(data.get("grace_years"), "寬限期")
            acc.start_date = _optional_date(data.get("start_date"), "撥款日")
            if acc.term_years is not None and acc.term_years == 0:
                raise EntryError("年期要大於 0")
            if acc.term_years and acc.grace_years and acc.grace_years >= acc.term_years:
                raise EntryError("寬限期要比年期短")
        elif type_ == "credit":
            acc.statement_day = _optional_day(data.get("statement_day"), "結帳日")
            acc.pay_day = _optional_day(data.get("pay_day"), "扣款日")
        autopay = str(data.get("autopay") or "").strip() if type_ == "credit" else ""
        if autopay and (acc.statement_day is None or acc.pay_day is None):
            raise EntryError("自動扣繳要先填結帳日和扣款日")
        rules = self._renamed_rules({acc.id: name}) if acc.id is not None else []
        saved = repo.save_account(self.db, acc)
        for r in rules:  # rules naming the old @帳戶 keep working
            repo.save_recurring(self.db, r)
        if type_ == "credit":
            acc.id = saved
            self._save_autopay(acc, autopay)
        return saved

    # ── 信用卡自動扣繳: one monthly 還 @卡 @付款帳戶 rule per card ──

    def _autopay_rule(self, card: Account) -> tuple[Recurring, str] | None:
        """The card's autopay rule and its paying account's name."""
        for r in repo.list_recurring(self.db):
            try:
                cmd = parse(r.line, self.today())
            except ParseError:
                continue
            if cmd.action != "repay" or cmd.amount is not None:
                continue
            names = [n for n in (cmd.account, cmd.to_account) if n]
            try:
                accs = [self._pick_account(Command("expense"), None, n) for n in names]
            except EntryError:
                continue
            if any(a.id == card.id for a in accs):
                payer = next((a.name for a in accs if a.id != card.id), "")
                return r, payer
        return None

    def autopay_accounts(self) -> dict[int, str]:
        """{card id: paying account} for the cards with an autopay rule."""
        out = {}
        for a in repo.list_accounts(self.db):
            if a.type == "credit" and (found := self._autopay_rule(a)):
                out[a.id or 0] = found[1]
        return out

    def _next_pay_date(self, card: Account) -> str:
        """The first 扣款日 after today: the bill already due today or earlier is not the rule's to pay."""
        assert card.pay_day is not None
        today = self.today()
        y, m = today.year, today.month
        while True:
            d = Date(y, m, min(card.pay_day, calendar.monthrange(y, m)[1]))
            if d > today:
                return d.isoformat()
            y, m = (y, m + 1) if m < 12 else (y + 1, 1)

    def _save_autopay(self, card: Account, payer: str) -> None:
        """Create, update or remove the card's autopay rule to match the account form."""
        found = self._autopay_rule(card)
        if not payer:
            if found:
                repo.delete_recurring(self.db, found[0].id or 0)
            return
        line = recurring._plain_line(self, format_command("repay", account=card.name, to_account=payer, note="卡費 自動扣繳"))
        if found is None:
            repo.save_recurring(self.db, Recurring(None, line, "monthly", self._next_pay_date(card)))
            return
        rule = found[0]
        moved = Date.fromisoformat(rule.start_date).day != card.pay_day
        if rule.line == line and not moved:
            return
        _, sep, note = rule.line.partition("#")
        rule.line = recurring._plain_line(self, format_command("repay", account=card.name, to_account=payer,
                                                              note=note.strip() if sep else "卡費 自動扣繳"))  # fmt: skip
        if moved:
            rule.start_date = self._next_pay_date(card)
        rule.error = None
        repo.save_recurring(self.db, rule)

    def delete_account(self, account_id: int) -> None:
        if repo.account_tx_count(self.db, account_id):
            raise EntryError("帳戶裡還有交易，不能刪除（可以封存）")
        repo.delete_account(self.db, account_id)

    # ── securities ──────────────────────────────────────────────────────

    def resolve_security(self, symbol: str) -> Security:
        symbol = normalize_symbol(symbol)
        sec = repo.get_security(self.db, symbol)
        if sec is not None:
            return sec
        if TW_CODE.match(symbol):
            if repo.count_tw_securities(self.db) == 0:
                raise EntryError("台股清單還沒下載，請等報價更新完成（或檢查網路）")
            hint = f"；港股請打 {int(symbol):04d}.HK" if symbol.isdigit() and len(symbol) <= 5 else ""
            raise EntryError(f"找不到台股代號 {symbol}{hint}")
        if symbol in self._us_misses:
            raise EntryError(self._us_misses[symbol])
        try:
            h = yahoo.chart(self.client, symbol)
        except ProviderError as e:
            if "找不到" in str(e):
                self._us_misses[symbol] = f"找不到代號 {symbol}"
            raise EntryError(f"找不到代號 {symbol}" if "找不到" in str(e) else str(e)) from e
        last = h.last
        sec = Security(
            symbol=symbol,
            name=h.name,
            market=market_of(symbol),
            currency=h.currency,
            kind=h.kind,
            last_close=last[1] if last else None,
            prev_close=h.prev_close,
            last_date=last[0] if last else None,
        )
        repo.upsert_securities(self.db, [sec])
        repo.put_prices(self.db, [(symbol, d, c) for d, c in h.closes])
        if sec.currency != "TWD" and repo.fx_on(self.db, sec.currency) is None:
            self._ensure_fx(sec.currency)  # so it can be valued right away, before the next refresh
        return sec

    # ── command line ────────────────────────────────────────────────────

    def _pick_account(self, cmd: Command, sec: Security | None, name: str | None = None) -> Account:
        """The account named by `name` (or cmd.account), else a sensible default for the line."""
        accounts = repo.list_accounts(self.db)
        if not accounts:
            raise EntryError("還沒有帳戶，先到「帳戶」新增一個")
        name = name if name is not None else cmd.account
        if name:
            q = name.lower()
            exact = [a for a in accounts if a.name.lower() == q]
            group = [a for a in accounts if (a.group_name or "").lower() == q]
            if not exact and group:
                # A multi-currency account: the security's currency picks the part.
                fit = [a for a in group if sec is not None and a.currency == sec.currency] or (group if len(group) == 1 else [])
                if not fit:
                    curs = "、".join(a.currency for a in group)
                    raise EntryError(f"「{group[0].group_name}」有 {curs} 多種幣別，請寫成 @{group[0].group_name}-{group[0].currency}")
                exact = fit[:1]
            found = exact or [a for a in accounts if q in a.name.lower()]
            if not found:
                raise EntryError(f"找不到帳戶「{name}」")
            if len(found) > 1:
                raise EntryError(f"「{name}」符合多個帳戶：{'、'.join(a.name for a in found)}")
            acc = found[0]
        elif sec is not None:
            wanted = "broker_tw" if sec.is_tw else "broker_us"
            found = [a for a in accounts if a.type == wanted and a.currency == sec.currency]
            if not found and not sec.is_tw:
                # 台幣交割: foreign stocks paid for in TWD from the brokerage settlement account.
                found = [a for a in accounts if a.type in BROKER_TYPES and a.currency == "TWD"]
            if not found:
                if sec.is_tw:
                    raise EntryError("還沒有台股券商帳戶，先到「帳戶」新增")
                raise EntryError(f"還沒有可以買 {sec.symbol} 的券商帳戶：新增台股券商（台幣交割）或 {sec.currency} 的複委託")
            acc = found[0]
        elif cmd.action in CATEGORY_KINDS and (
            found := [a for a in accounts if a.type in SPENDING_TYPES and a.currency == "TWD"]
            or [a for a in accounts if a.type in SPENDING_TYPES]
        ):
            acc = found[0]
        elif len(accounts) == 1:
            acc = accounts[0]
        else:
            raise EntryError("有多個帳戶，請用 @帳戶名稱 指定")
        if sec is not None and acc.currency != sec.currency:
            settles_in_twd = not sec.is_tw and acc.currency == "TWD" and acc.type in BROKER_TYPES
            if not settles_in_twd:
                raise EntryError(f"{sec.symbol} 以 {sec.currency} 交易，帳戶「{acc.name}」是 {acc.currency}")
        return acc

    def _rate(self, acc: Account, day: str, override: Decimal | None) -> Decimal | None:
        """TWD per unit of the account's currency for a transaction; None for TWD accounts."""
        if acc.currency == "TWD":
            return None
        if override is not None:
            return override
        if (found := repo.fx_on(self.db, acc.currency, day)) is not None:
            return found[0]
        raise EntryError(f"還沒有 {acc.currency} 匯率，等報價更新或用「匯 31.9」指定")

    def _edit_ids(self, edit_id: int | None) -> set[int]:
        """The rows an edit replaces: the transaction, or both legs of a transfer."""
        if edit_id is None:
            return set()
        t = repo.get_tx(self.db, edit_id)
        if t is None:
            raise EntryError("這筆交易已經不存在")
        if t.transfer_group:
            return {x.id for x in repo.txs_in_group(self.db, t.transfer_group) if x.id is not None}
        return {edit_id}

    def _resolve_category(self, name: str | None, kind: str) -> tuple[Category | None, str]:
        """(existing category, display name); a None category means it is created on commit."""
        cats = [c for c in repo.list_categories(self.db, kind) if not c.archived]
        if not name:
            name = "其他" if kind == "expense" else "其他收入"
        exact = [c for c in cats if c.name == name]
        if exact:
            return exact[0], name
        partial = [c for c in cats if name in c.name]
        if len(partial) == 1:
            return partial[0], partial[0].name
        return None, name

    def _guess_category(self, note: str, kind: str, skip: set[int]) -> Category | None:
        """A category from the last year's entries of the same kind: the latest with the same note, else
        notes containing one another when they all agree on one category."""
        note = note.strip()
        if not note:
            return None
        cats = {c.id: c for c in repo.list_categories(self.db, kind) if not c.archived}
        since = (self.today() - timedelta(days=GUESS_DAYS)).isoformat()
        past = [
            t for t in repo.list_txs(self.db)
            if t.kind == kind and t.category_id in cats and t.date >= since and t.note.strip()
            and t.id not in skip and not t.transfer_group
        ]  # fmt: skip
        same = [t for t in past if t.note.strip() == note]
        if same:
            return cats[same[-1].category_id]
        if len(note) < 2:
            return None
        near = {t.category_id for t in past if note in t.note or t.note.strip() in note}
        return cats[near.pop()] if len(near) == 1 else None

    def build(self, cmd: Command, edit_id: int | None = None) -> Draft:
        """Resolve a parsed command into ready-to-save transactions, or raise EntryError."""
        if cmd.missing:
            raise EntryError("還缺：" + "、".join(FIELD_NAMES[m] for m in cmd.missing))
        today = self.today().isoformat()
        day = cmd.date or today
        if day > today:
            raise EntryError("日期不能在未來")
        if cmd.interest is not None and cmd.action != "repay":
            raise EntryError("「利」只用在還款")
        skip = self._edit_ids(edit_id)
        keep_id = edit_id if len(skip) == 1 and cmd.action not in ("transfer", "repay") else None
        if cmd.action == "transfer":
            draft = self._build_transfer(cmd, day)
        elif cmd.action == "repay":
            draft = self._build_repay(cmd, day, skip)
        elif cmd.action == "dca":
            draft = self._build_dca(cmd, day, keep_id)
        elif cmd.action in CATEGORY_KINDS:
            draft = self._build_flow(cmd, day, keep_id, skip)
        else:
            draft = self._build_trade(cmd, day, keep_id)
        self._check(draft.txs, skip)
        return draft

    def _build_flow(self, cmd: Command, day: str, keep_id: int | None, skip: set[int]) -> Draft:
        assert cmd.amount is not None
        acc = self._pick_account(cmd, None)
        guess = self._guess_category(cmd.note, cmd.action, skip) if cmd.category is None else None
        cat, cat_name = (guess, guess.name) if guess else self._resolve_category(cmd.category, cmd.action)
        tx = Tx(
            id=keep_id,
            account_id=acc.id or 0,
            date=day,
            kind=cmd.action,
            amount=cmd.amount if cmd.action == "income" else -cmd.amount,
            fx_rate=self._rate(acc, day, cmd.fx),
            category_id=cat.id if cat else None,
            note=cmd.note,
        )
        return Draft([tx], acc, category=cat_name, new_category=None if cat else cat_name, guessed=guess is not None)

    def _build_transfer(self, cmd: Command, day: str) -> Draft:
        assert cmd.amount is not None
        if not cmd.account or not cmd.to_account:
            raise EntryError("轉帳要寫兩個帳戶：@轉出帳戶 @轉入帳戶")
        src = self._pick_account(cmd, None, cmd.account)
        dst = self._pick_account(cmd, None, cmd.to_account)
        if src.id == dst.id:
            raise EntryError("轉出和轉入是同一個帳戶")
        if src.currency != "TWD" and dst.currency != "TWD" and cmd.fx is not None:
            raise EntryError("兩邊都是外幣時不能用「匯」，會用當天匯率換算")
        r_src = self._rate(src, day, cmd.fx) or Decimal(1)
        r_dst = self._rate(dst, day, cmd.fx) or Decimal(1)
        if cmd.fx is None and src.currency == "TWD" and dst.currency != "TWD":
            # Buying foreign currency: the bank charges its selling rate, when we have the board.
            r_dst = repo.fx_sell_on(self.db, dst.currency, day) or r_dst
        received = fmt.round_money(cmd.amount * r_src / r_dst, dst.currency)
        group = uuid.uuid4().hex
        legs = [
            Tx(None, src.id or 0, day, "transfer", amount=-cmd.amount, fx_rate=r_src if src.currency != "TWD" else None,
               transfer_group=group, note=cmd.note),
            Tx(None, dst.id or 0, day, "transfer", amount=received, fx_rate=r_dst if dst.currency != "TWD" else None,
               transfer_group=group, note=cmd.note),
        ]  # fmt: skip
        return Draft(legs, src, to_account=dst)

    # ── 定期定額 ──

    def _close_ready(self, sec: Security, day: str) -> bool:
        """A close is final for days before today; today's only after the Taiwan close is out."""
        today = self.today()
        if day < today.isoformat():
            return True
        now = taipei_now()
        return day == today.isoformat() and sec.is_tw and now.date() == today and now.time() >= time(14, 30)

    def _dca_close(self, sec: Security, day: str) -> tuple[str, Decimal]:
        """(trade date, close): the first trading day on or after `day` whose close is final."""
        def first() -> tuple[str, Decimal] | None:
            return next(((d, c) for d, c in repo.closes_from(self.db, sec.symbol, day) if self._close_ready(sec, d)), None)

        found = first()
        if (found is None or found[0] != day) and (sec.symbol, day) not in self._filled:
            # Prices are stored only for days the app refreshed; fill gaps from Yahoo's daily bars.
            self._filled.add((sec.symbol, day))
            age = (self.today() - Date.fromisoformat(day)).days
            ysym = f"{sec.symbol}.TW" if sec.market == "TWSE" else f"{sec.symbol}.TWO" if sec.market == "TPEX" else sec.symbol
            try:
                h = yahoo.chart(self.client, ysym, "1mo" if age < 25 else "6mo" if age < 170 else "5y")
                repo.put_prices(self.db, [(sec.symbol, d, c) for d, c in h.closes])
                found = first()
            except ProviderError as e:
                log.info("定額 %s: %s", sec.symbol, e)
        if found is None:
            raise QuoteNotYet(f"還沒有 {sec.symbol} {day} 的收盤價，收盤後會自動記", day)
        return found

    def _build_dca(self, cmd: Command, day: str, keep_id: int | None) -> Draft:
        assert cmd.symbol is not None and cmd.amount is not None
        sec = self.resolve_security(cmd.symbol)
        trade_day, close = self._dca_close(sec, day)
        qty = cmd.amount / close
        qty = qty.to_integral_value(rounding=ROUND_FLOOR) if sec.is_tw else qty.quantize(Decimal("0.0001"), rounding=ROUND_FLOOR)
        if qty <= 0:
            raise EntryError(f"{fmt.money(cmd.amount, sec.currency)} 不夠買 1 股（收盤 {fmt.price(close)}）")
        buy = Command("buy", symbol=sec.symbol, qty=qty, price=close, date=trade_day, account=cmd.account,
                      fee=cmd.fee, note=cmd.note or DCA_NOTE)  # fmt: skip
        draft = self._build_trade(buy, trade_day, keep_id)
        draft.dca = cmd.amount
        return draft

    # ── 期初餘額 ──

    @staticmethod
    def _precedes(x: Tx, day: str, opening_id: int | None) -> bool:
        """Whether row x is part of an opening balance on `day`: dated earlier, or the same day and recorded
        before it (a new opening, without an id yet, comes after everything already recorded)."""
        if x.date != day:
            return x.date < day
        return x.id is not None and x.id != opening_id and (opening_id is None or x.id < opening_id)

    def _before(self, account_id: int, day: str, opening_id: int | None) -> Decimal:
        """What the account's rows before an opening balance add up to (the opening is net of these)."""
        return sum((t.amount for t in repo.list_txs(self.db) if t.account_id == account_id and self._precedes(t, day, opening_id)), ZERO)

    def _rebase(self) -> None:
        """Re-derive every 期初餘額 amount after a change: balance − the account's earlier rows."""
        txs = repo.list_txs(self.db)  # date, id order: earlier openings are settled first
        before: dict[int, list[Tx]] = {}
        changed: list[tuple[int, Decimal]] = []
        for t in txs:
            if t.balance is not None and t.id is not None:
                amount = t.balance - sum((x.amount for x in before.get(t.account_id, []) if self._precedes(x, t.date, t.id)), ZERO)
                if amount != t.amount:
                    t.amount = amount
                    changed.append((t.id, amount))
            before.setdefault(t.account_id, []).append(t)
        if changed:
            repo.set_tx_amounts(self.db, changed)

    def _convert_openings(self) -> None:
        """Once: each account's first-entered deposit becomes its 期初餘額 (balance = what the account
        held when it was entered), then amounts are re-derived. See DESIGN.md 5.1."""
        if repo.get_setting(self.db, "openings_converted", "") == "1":
            return
        txs = repo.list_txs(self.db)
        for acc in {t.account_id for t in txs}:
            rows = [t for t in txs if t.account_id == acc]
            if any(t.balance is not None for t in rows):
                continue
            deposits = [t for t in rows if t.kind == "deposit" and t.id is not None]
            if not deposits:
                continue
            first = min(deposits, key=lambda t: t.id or 0)
            held = first.amount + sum((t.amount for t in rows if (t.id or 0) < (first.id or 0) and t.date < first.date), ZERO)
            repo.set_tx_balance(self.db, first.id or 0, held)
        self._rebase()
        repo.set_setting(self.db, "openings_converted", "1")

    # ── loans ──

    def _owed(self, loan: Account, day: str, skip: set[int]) -> Decimal:
        """What is still owed on a loan account on `day` (its balance, sign flipped)."""
        return -sum((t.amount for t in repo.list_txs(self.db) if t.account_id == loan.id and t.date <= day and t.id not in skip), ZERO)

    @staticmethod
    def _schedule(loan: Account) -> planner.Loan | None:
        if not (loan.principal and loan.rate is not None and loan.term_years):
            return None
        return planner.amortize(float(loan.principal), float(loan.rate) / 100, float(loan.term_years), float(loan.grace_years or 0))

    @staticmethod
    def _period(loan: Account, day: str) -> int:
        """Which instalment a payment in `day`'s month is (1 = the month after the drawdown)."""
        if not loan.start_date:
            return 1
        s, d = Date.fromisoformat(loan.start_date), Date.fromisoformat(day)
        return max(1, (d.year - s.year) * 12 + d.month - s.month)

    def _scheduled_payment(self, loan: Account, day: str) -> Decimal | None:
        sched = self._schedule(loan)
        if sched is None:
            return None
        k = min(self._period(loan, day), sched.months)
        return fmt.round_money(Decimal(str(sched.at(k))), loan.currency)

    def _interest(self, loan: Account, owed: Decimal) -> Decimal:
        return fmt.round_money(owed * (loan.rate or ZERO) / 100 / 12, loan.currency)

    def _build_repay(self, cmd: Command, day: str, skip: set[int]) -> Draft:
        names = [n for n in (cmd.account, cmd.to_account) if n]
        if not names:
            raise EntryError("還款要寫貸款或信用卡帳戶：還 @房貸、還 @玉山")
        accs = [self._pick_account(cmd, None, n) for n in names]
        cards = [a for a in accs if a.type == "credit"]
        loans = [a for a in accs if a.type == "loan"]
        if cards and not loans:
            return self._build_card_payment(cmd, day, skip, accs, cards)
        if len(loans) != 1:
            raise EntryError("兩個都是貸款帳戶" if loans else "還款要指定一個貸款帳戶或信用卡")
        loan = loans[0]
        payer = next((a for a in accs if a is not loan), None) or self._pick_account(Command("expense"), None)
        if payer.type == "loan":
            raise EntryError("付款帳戶不能是貸款帳戶")
        if payer.currency != loan.currency:
            raise EntryError(f"付款帳戶「{payer.name}」和貸款的幣別不同")
        owed = self._owed(loan, day, skip)
        if owed <= 0:
            raise EntryError(f"「{loan.name}」已經還清了")
        interest = cmd.interest if cmd.interest is not None else self._interest(loan, owed)
        amount = cmd.amount if cmd.amount is not None else self._scheduled_payment(loan, day)
        if amount is None:
            raise EntryError(f"「{loan.name}」沒有設定貸款金額、利率和年期，請寫金額：還 30000 @{loan.name}")
        if amount < interest:
            raise EntryError(f"金額比這期利息 {fmt.money(interest, loan.currency)} 還少")
        principal = min(amount - interest, owed)
        rate = self._rate(payer, day, None)
        group = uuid.uuid4().hex
        # The loan leg is kept even at 0 (grace period): it is what ties the group to its loan.
        txs = [Tx(None, loan.id or 0, day, "transfer", amount=principal, fx_rate=rate, transfer_group=group, note=cmd.note)]
        if principal:
            txs.insert(0, Tx(None, payer.id or 0, day, "transfer", amount=-principal, fx_rate=rate, transfer_group=group, note=cmd.note))
        cat, cat_name = self._resolve_category(LOAN_INTEREST, "expense")
        if interest:
            txs.append(Tx(None, payer.id or 0, day, "expense", amount=-interest, fx_rate=rate,
                          category_id=cat.id if cat else None, transfer_group=group, note=cmd.note))  # fmt: skip
        return Draft(
            txs, payer, to_account=loan, category=cat_name, new_category=None if cat or not interest else cat_name,
            repay={"principal": principal, "interest": interest, "owed": owed},
        )

    # ── credit cards ──

    @staticmethod
    def _statement_date(card: Account, day: str) -> str:
        """The last 結帳日 before `day` (a 31st falls on a shorter month's last day)."""
        assert card.statement_day is not None
        d = Date.fromisoformat(day)
        y, m = d.year, d.month
        while True:
            closing = Date(y, m, min(card.statement_day, calendar.monthrange(y, m)[1]))
            if closing < d:
                return closing.isoformat()
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)

    def _card_due(self, card: Account, day: str, skip: set[int]) -> dict[str, Any]:
        """The bill paid on `day`: what was owed on the last 結帳日, less what was paid in (or refunded) since."""
        statement = self._statement_date(card, day)
        rows = [t for t in repo.list_txs(self.db) if t.account_id == card.id and t.date <= day and t.id not in skip]
        owed = max(-sum((t.amount for t in rows if t.date <= statement), ZERO), ZERO)
        paid = sum((t.amount for t in rows if t.date > statement and t.amount > 0), ZERO)
        return {"statement": statement, "owed": owed, "paid": paid, "due": max(owed - paid, ZERO)}

    def _build_card_payment(self, cmd: Command, day: str, skip: set[int], accs: list[Account], cards: list[Account]) -> Draft:
        """還 @卡 @銀行: pays the bill (or the amount written) as a transfer into the card."""
        if len(cards) != 1:
            raise EntryError("兩個都是信用卡帳戶")
        card = cards[0]
        payer = next((a for a in accs if a is not card), None) or self._pick_account(Command("expense"), None)
        if payer.type in ("credit", "loan"):
            raise EntryError("付款帳戶不能是信用卡或貸款帳戶")
        if payer.currency != card.currency:
            raise EntryError(f"付款帳戶「{payer.name}」和信用卡的幣別不同")
        if cmd.interest is not None:
            raise EntryError("信用卡繳費不用寫「利」")
        bill = None
        if cmd.amount is not None:
            amount = cmd.amount
        elif card.statement_day is None:
            raise EntryError(f"「{card.name}」沒有設定結帳日，請寫金額：還 3000 @{card.name}")
        else:
            bill = self._card_due(card, day, skip)
            amount = bill["due"]
            if amount <= 0:
                raise NothingDue("這期帳單已經繳清")
        rate = self._rate(payer, day, None)
        group = uuid.uuid4().hex
        txs = [Tx(None, payer.id or 0, day, "transfer", amount=-amount, fx_rate=rate, transfer_group=group, note=cmd.note),
               Tx(None, card.id or 0, day, "transfer", amount=amount, fx_rate=rate, transfer_group=group, note=cmd.note)]  # fmt: skip
        return Draft(txs, payer, to_account=card, bill=bill)

    def _build_trade(self, cmd: Command, day: str, keep_id: int | None) -> Draft:
        sec = self.resolve_security(cmd.symbol) if cmd.symbol else None
        acc = self._pick_account(cmd, sec)
        cur = acc.currency

        fee = tax = ZERO
        qty = price = None
        # 台幣交割: a foreign security bought/sold through a TWD account; the broker converts at its rate.
        cross = sec is not None and sec.currency != cur
        trade_fx: Decimal | None = None
        if cross and cmd.action in ("buy", "sell", "holding_in", "cash_dividend", "stock_dividend", "split"):
            assert sec is not None
            trade_fx = cmd.fx if cmd.fx is not None else self._conversion_rate(sec.currency, day, buying=cmd.action != "sell")
        if cmd.action in ("buy", "sell", "holding_in"):
            assert sec is not None and cmd.qty is not None and cmd.price is not None
            qty, price = cmd.qty, cmd.price
            gross = qty * price
            if cross:
                assert trade_fx is not None
                gross = fmt.round_money(gross * trade_fx, cur)  # foreign amount converted to the settlement currency
            elif cur == "TWD":
                gross = gross.to_integral_value(rounding=ROUND_FLOOR)  # brokers truncate odd-lot amounts
            else:
                gross = fmt.round_money(gross, cur)
            auto_fee, auto_tax = self._auto_fees(sec, acc, cmd.action, gross, qty * price, trade_fx, day)
            fee = cmd.fee if cmd.fee is not None else auto_fee
            tax = cmd.tax if cmd.tax is not None else auto_tax
            if cmd.action == "holding_in" and cmd.total is not None:
                # The broker app's 總成本 (fees and conversion included) is the cost basis, exactly.
                if cmd.total <= 0:
                    raise EntryError("總成本要大於 0")
                if cross:
                    trade_fx = (cmd.total / (qty * price)).quantize(Decimal("0.0000000001"))
                    fee = tax = ZERO
                else:
                    fee, tax = cmd.total - gross, ZERO
                    if fee < 0:
                        raise EntryError("總成本比 股數 × 成交均價 還少，請確認數字")
            elif cmd.total is not None:
                raise EntryError("「總」只用在補登持股")
            if cmd.action == "holding_in":
                amount = ZERO  # the money already left the recorded balance
            else:
                amount = -(gross + fee + tax) if cmd.action == "buy" else gross - fee - tax
        elif cmd.action == "cash_dividend":
            assert cmd.amount is not None
            amount = cmd.amount
            if cmd.gross:  # 稅前: take off 預扣稅／二代健保 (or the 稅 written); what's stored is what arrived
                assert sec is not None
                auto, _ = dividends.dividend_tax(cmd.amount, sec.market, cur)
                tax = cmd.tax if cmd.tax is not None else auto
                if tax > cmd.amount:
                    raise EntryError("稅比股利還多，請確認數字")
                amount = cmd.amount - tax
        elif cmd.action in ("stock_dividend", "split"):
            qty = cmd.qty
            amount = ZERO
        elif cmd.action == "deposit":
            assert cmd.amount is not None
            amount = cmd.amount
        else:  # withdraw
            assert cmd.amount is not None
            amount = -cmd.amount
        opening = cmd.amount if cmd.opening else None
        if opening is not None:  # 期初餘額: what this row adds is the stated balance minus what came before
            amount = opening - self._before(acc.id or 0, day, keep_id)

        tx = Tx(
            id=keep_id,
            account_id=acc.id or 0,
            date=day,
            kind=cmd.action,
            symbol=sec.symbol if sec else None,
            qty=qty,
            price=price,
            amount=amount,
            fee=fee,
            tax=tax,
            # On a TWD account fx_rate is only set for 台幣交割 trades: the conversion rate used.
            fx_rate=trade_fx if cross else self._rate(acc, day, cmd.fx),
            note=cmd.note,
            balance=opening,
        )
        return Draft([tx], acc, sec)

    def _auto_fees(
        self, sec: Security, acc: Account, action: str, gross: Decimal, gross_sec: Decimal, fx: Decimal | None, day: str
    ) -> tuple[Decimal, Decimal]:
        """(fee, tax) in the account's currency when the line gives none.

        Taiwan: brokerage fee (account/global discount) and, on sells, transaction tax.
        Hong Kong: 國泰複委託 online-order schedule in HKD, converted at the trade rate for 台幣交割.
        Elsewhere: unknown, so 0 (the user fills in the statement amount).
        """
        if sec.is_tw:
            fee = fees.tw_fee(gross, *self._fee_terms(acc))
            tax = fees.tw_tax(gross, sec.kind, day) if action == "sell" else ZERO
            return fee, tax
        if sec.market == "HK":
            fee, tax = fees.hk_fees(fmt.round_money(gross_sec, sec.currency), sec.kind)
            if fx is not None and acc.currency != sec.currency:
                return fmt.round_money(fee * fx, acc.currency), fmt.round_money(tax * fx, acc.currency)
            return fee, tax
        return ZERO, ZERO

    def _conversion_rate(self, currency: str, day: str, buying: bool) -> Decimal:
        """Rate for converting a foreign trade to TWD: the bank's selling rate when buying (if we have the
        board), otherwise that day's rate; fetched on demand for a currency we have never needed."""
        if buying and (sell := repo.fx_sell_on(self.db, currency, day)) is not None:
            return sell
        found = repo.fx_on(self.db, currency, day) or self._ensure_fx(currency)
        if found is None:
            raise EntryError(f"還沒有 {currency} 匯率，請用「匯」指定成交匯率")
        return found[0]

    def _ensure_fx(self, currency: str) -> tuple[Decimal, str] | None:
        try:
            h = yahoo.chart(self.client, yahoo.fx_symbol(currency))
            repo.put_fx(self.db, [(currency, d, r) for d, r in h.closes])
        except ProviderError:
            return None
        return repo.fx_on(self.db, currency)

    def _check(self, new: list[Tx], skip_ids: set[int]) -> Book:
        """Replay the whole book with `new` in place of `skip_ids`; raises on overselling."""
        txs = [t for t in repo.list_txs(self.db) if t.id not in skip_ids] + new
        txs.sort(key=lambda t: (t.date, t.id if t.id is not None else 1 << 62))
        try:
            return self._replay(txs)
        except PortfolioError as e:
            raise EntryError(str(e)) from e

    def _replay(self, txs: list[Tx]) -> Book:
        currency_of = {a.id or 0: a.currency for a in repo.list_accounts(self.db, True)}

        def fx(cur: str, day: str) -> Decimal:
            found = repo.fx_on(self.db, cur, day)
            return found[0] if found else ZERO

        return replay(txs, currency_of, fx)

    def preview(self, text: str, edit_id: int | None = None) -> dict[str, Any]:
        try:
            cmd = parse(text, self.today())
        except ParseError as e:
            return {"status": "empty"} if not str(e) else {"status": "error", "message": str(e)}
        if cmd.action == "lookup":
            return self._lookup(cmd.symbol or "")
        try:
            sec_title = None
            if cmd.symbol:
                sec = self.resolve_security(cmd.symbol)
                sec_title = f"{sec.name} {sec.symbol}"
            if cmd.missing:
                return {
                    "status": "incomplete",
                    "title": sec_title,
                    "message": "還缺：" + "、".join(FIELD_NAMES[m] for m in cmd.missing),
                }
            draft = self.build(cmd, edit_id)
        except QuoteNotYet as e:  # 定額 before the close: show what it will do
            assert cmd.amount is not None
            return {"status": "ready", "title": f"定期定額 {sec_title or cmd.symbol}", "parts": [str(e)],
                    "total": fmt.money(-cmd.amount, signed=True), "currency": "TWD", "sign": -1}  # fmt: skip
        except NothingDue as e:  # still a valid line, e.g. for an autopay rule
            return {"status": "error", "message": str(e), "settled": True}
        except EntryError as e:
            return {"status": "error", "message": str(e)}
        return {"status": "ready", **self._describe(draft), "guessed_category": draft.category if draft.guessed else None}

    def _describe(self, d: Draft) -> dict[str, Any]:
        t, cur = d.tx, d.account.currency
        parts: list[str] = []
        if d.repay is not None and d.to_account is not None:
            r = d.repay
            parts += [f"本金 {fmt.money(r['principal'], cur)}", f"利息 {fmt.money(r['interest'], cur)}",
                      f"還完剩 {fmt.money(r['owed'] - r['principal'], cur)}", d.account.name]  # fmt: skip
            if t.date != self.today().isoformat():
                parts.append(t.date)
            if t.note:
                parts.append(t.note)
            total = r["principal"] + r["interest"]
            return {"title": f"還款 {d.to_account.name}", "parts": parts, "total": fmt.money(-total, cur, signed=True),
                    "currency": cur, "sign": -1}  # fmt: skip
        if t.kind == "transfer" and d.to_account is not None and d.to_account.type == "credit" and d.txs[1].account_id == d.to_account.id:
            if (b := d.bill) is not None:
                parts.append(f"{b['statement'][5:].replace('-', '/')} 帳單 {fmt.money(b['owed'], cur)}")
                if b["paid"]:
                    parts.append(f"已繳 −{fmt.money(b['paid'], cur)}")
            parts.append(d.account.name)
            if t.date != self.today().isoformat():
                parts.append(t.date)
            if t.note:
                parts.append(t.note)
            return {"title": f"繳卡費 {d.to_account.name}", "parts": parts, "total": fmt.money(t.amount, cur, signed=True),
                    "currency": cur, "sign": -1, "card": True}  # fmt: skip
        if t.kind == "transfer" and d.to_account is not None:
            got = d.txs[1].amount
            title = f"轉帳 {d.account.name} → {d.to_account.name}"
            if d.to_account.currency != cur:
                parts.append(f"轉入 {fmt.money(got, d.to_account.currency)} {d.to_account.currency}")
                rate = d.txs[0].fx_rate or d.txs[1].fx_rate
                parts.append(f"匯率 {rate}")
            if t.date != self.today().isoformat():
                parts.append(t.date)
            if t.note:
                parts.append(t.note)
            return {"title": title, "parts": parts, "total": fmt.money(t.amount, cur, signed=True),
                    "currency": cur, "sign": -1}  # fmt: skip
        if t.balance is not None:
            owed = t.balance < 0
            parts.append(f"{d.account.name}在這天的{'欠款' if owed else '餘額'}")
            if t.amount != t.balance:  # the earlier rows it already includes
                parts.append(f"已含之前記的 {fmt.money(abs(t.balance - t.amount), cur)}")
            if t.date != self.today().isoformat():
                parts.append(t.date)
            if t.note:
                parts.append(t.note)
            return {"title": f"期初{'欠款' if t.balance < 0 else '餘額'} {d.account.name}", "parts": parts, "total": fmt.money(t.balance, cur),
                    "currency": cur, "sign": fmt.sign(t.balance)}  # fmt: skip
        if t.kind in CATEGORY_KINDS:
            title = f"{TX_KINDS[t.kind]} {d.category}"
            if d.new_category:
                parts.append("新分類")
            elif d.guessed:
                parts.append("依過去紀錄")
            parts.append(d.account.name)
        else:
            name = f"{d.security.name} {d.security.symbol}" if d.security else d.account.name
            title = f"{TX_KINDS[t.kind]} {name}"
        if d.dca is not None:
            parts.append(f"定期定額 {fmt.money(d.dca, cur)}，{t.date} 收盤價")
        if t.kind in ("buy", "sell", "holding_in"):
            parts.append(f"{fmt.qty(t.qty)} 股 @ {fmt.price(t.price)}")
        elif t.kind == "stock_dividend":
            parts.append(f"配 {fmt.qty(t.qty)} 股")
        elif t.kind == "split":
            parts.append(f"1 股變 {fmt.qty(t.qty)} 股")
        if t.fee:
            parts.append(f"手續費 {fmt.money(t.fee, cur)}")
        if t.tax and t.kind == "cash_dividend":
            label = dividends.dividend_tax(t.amount + t.tax, d.security.market, cur)[1] if d.security else None
            parts.append(f"稅前 {fmt.money(t.amount + t.tax, cur)} − {label or '稅'} {fmt.money(t.tax, cur)}")
        elif t.tax:
            parts.append(f"證交稅 {fmt.money(t.tax, cur)}")
        if t.fx_rate is not None:
            parts.append(f"匯率 {t.fx_rate}")
        if d.security:
            parts.append(d.account.name)
        if t.kind == "holding_in":
            parts.append("不從現金扣款")
            if t.date == self.today().isoformat():
                parts.append("日期請改成當初買進那天")
        if t.date != self.today().isoformat():
            parts.append(t.date)
        if t.note:
            parts.append(t.note)
        return {
            "title": title,
            "parts": parts,
            "total": fmt.money(t.amount, cur, signed=True) if t.amount else None,
            "currency": cur,
            "sign": fmt.sign(t.amount),
        }

    def _lookup(self, q: str) -> dict[str, Any]:
        sym = normalize_symbol(q.upper())
        found = repo.search_securities(self.db, sym if sym != q.upper() else q)
        if q.isdigit() and len(q) <= 5:
            # A bare number may be a Hong Kong code (0700 = 騰訊); offer it after any Taiwan matches.
            try:
                hk = self.resolve_security(f"{int(q):04d}.HK")
                if all(s.symbol != hk.symbol for s in found):
                    found = [*found[:5], hk]
            except EntryError:
                pass
        if not found and not TW_CODE.match(sym) and FOREIGN_SYMBOL.fullmatch(sym):
            try:
                found = [self.resolve_security(sym)]
            except EntryError:
                found = []
        if not found and not q.isdigit() and len(q) >= 2:
            try:  # English name search (Yahoo has no Chinese names): tencent, apple...
                hits = yahoo.search(self.client, q)[:5]
            except ProviderError:
                hits = []
            if hits:
                return {
                    "status": "lookup",
                    "results": [
                        {"symbol": s, "name": n, "close": None, "change": None, "sign": 0, "date": None, "held": None}
                        for s, n, _ in hits
                    ],
                }
        if not found:
            return {"status": "error", "message": f"找不到「{q}」；記一筆請用 買、賣、息、支出、收入、轉… 開頭"}
        book = self._replay(repo.list_txs(self.db))
        held: dict[str, Decimal] = {}
        for p in book.open_positions():
            held[p.symbol] = held.get(p.symbol, ZERO) + p.qty
        return {
            "status": "lookup",
            "results": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "close": fmt.price(s.last_close),
                    "change": fmt.pct(s.last_close - s.prev_close, s.prev_close)
                    if s.last_close is not None and s.prev_close
                    else None,
                    "sign": fmt.sign(s.last_close - s.prev_close) if s.last_close and s.prev_close else 0,
                    "date": s.last_date,
                    "held": fmt.qty(held[s.symbol]) if s.symbol in held else None,
                }
                for s in found
            ],
        }

    def adopt(self, text: str, recurring_id: int) -> bool:
        """週期性: when the entry a rule is about to post was already recorded by hand (same account, kind,
        amount, category, note and date, not tied to a rule), tie that one to the rule instead."""
        with self._lock:
            draft = self.build(parse(text, self.today()))
            if len(draft.txs) != 1:
                return False
            t = draft.tx
            key = (t.account_id, t.date, t.kind, t.amount, t.category_id, t.symbol, t.qty, t.note.strip())
            for x in repo.list_txs(self.db):
                if x.recurring_id is None and not x.transfer_group and x.id is not None and (
                    x.account_id, x.date, x.kind, x.amount, x.category_id, x.symbol, x.qty, x.note.strip()
                ) == key:
                    repo.mark_recurring(self.db, x.id, recurring_id)
                    return True
            return False

    def commit(self, text: str, edit_id: int | None = None, recurring_id: int | None = None) -> int:
        with self._lock:
            try:
                cmd = parse(text, self.today())
            except ParseError as e:
                raise EntryError(str(e) or "沒有輸入內容") from e
            if cmd.action == "lookup":
                raise EntryError("記一筆請用 買、賣、息、配股、拆、存、提、支出、收入、轉 開頭")
            skip = self._edit_ids(edit_id)
            draft = self.build(cmd, edit_id)
            if draft.new_category:
                new_id = repo.add_category(self.db, draft.new_category, "expense" if cmd.action == "repay" else cmd.action)
                for t in draft.txs:
                    if t.kind in CATEGORY_KINDS and t.category_id is None:
                        t.category_id = new_id
            if recurring_id is None and edit_id is not None:
                old = repo.get_tx(self.db, edit_id)
                recurring_id = old.recurring_id if old else None  # an edited posting stays marked as recurring
                t = draft.tx
                if (old and recurring_id in recurring.dca_rules(self) and len(draft.txs) == 1 and t.kind == "buy"
                        and t.note == DCA_NOTE and (t.qty, t.price) != (old.qty, old.price)):
                    t.note = DCA_CONFIRMED  # corrected to the broker's fill: no longer the close-price estimate
            for t in draft.txs:
                t.recurring_id = recurring_id
            if len(draft.txs) == 1 and draft.tx.id is not None:
                tx_id = repo.save_tx(self.db, draft.tx)  # plain edit keeps its id (and same-day order)
            else:
                tx_id = repo.replace_txs(self.db, sorted(skip), draft.txs)[0]
            self._rebase()
            self.snapshot()
            return tx_id

    def delete(self, tx_id: int) -> None:
        with self._lock:
            ids = self._edit_ids(tx_id)
            self._check([], ids)
            repo.replace_txs(self.db, sorted(ids), [])
            self._rebase()
            self.snapshot()

    def tx_line(self, tx_id: int) -> str:
        """The command line that recreates a stored transaction, for editing in place."""
        t = repo.get_tx(self.db, tx_id)
        if t is None:
            raise EntryError("這筆交易已經不存在")
        acc = repo.get_account(self.db, t.account_id)
        if t.transfer_group and (repay := self._repay_parts(repo.txs_in_group(self.db, t.transfer_group))):
            loan, payer, principal, interest = repay
            owed = self._owed(loan, t.date, {x.id for x in repo.txs_in_group(self.db, t.transfer_group) if x.id})
            return format_command(
                "repay", amount=principal + interest, date=t.date, account=loan.name, to_account=payer.name,
                interest=interest if interest != self._interest(loan, owed) else None, note=t.note,
            )  # fmt: skip
        if t.kind == "transfer" and t.transfer_group:
            legs = repo.txs_in_group(self.db, t.transfer_group)
            out = next((x for x in legs if x.amount < 0), t)
            inn = next((x for x in legs if x.amount >= 0), t)
            a_out, a_in = repo.get_account(self.db, out.account_id), repo.get_account(self.db, inn.account_id)
            cross = a_out and a_in and a_out.currency != a_in.currency and "TWD" in (a_out.currency, a_in.currency)
            return format_command(
                "transfer",
                amount=-out.amount,
                date=t.date,
                account=a_out.name if a_out else None,
                to_account=a_in.name if a_in else None,
                fx=(out.fx_rate or inn.fx_rate) if cross else None,
                note=t.note,
            )
        if t.kind in CATEGORY_KINDS:
            cat = repo.get_category(self.db, t.category_id) if t.category_id else None
            fx = None
            if t.fx_rate is not None and acc is not None:
                on_day = repo.fx_on(self.db, acc.currency, t.date)
                fx = t.fx_rate if on_day is None or on_day[0] != t.fx_rate else None
            return format_command(
                t.kind, amount=abs(t.amount), category=cat.name if cat else None, date=t.date,
                account=acc.name if acc else None, fx=fx, note=t.note,
            )  # fmt: skip
        sec = repo.get_security(self.db, t.symbol) if t.symbol else None
        fee = tax = None
        if t.kind in ("buy", "sell", "holding_in") and sec is not None and acc is not None:
            # Only spell out fee/tax when they differ from what would be computed anyway.
            cross_fx = t.fx_rate if acc.currency == "TWD" and sec.currency != "TWD" else None
            gross_sec = (t.qty or ZERO) * (t.price or ZERO)
            if cross_fx is not None:
                gross = fmt.round_money(gross_sec * cross_fx, acc.currency)
            elif acc.currency == "TWD":
                gross = gross_sec.to_integral_value(rounding=ROUND_FLOOR)
            else:
                gross = fmt.round_money(gross_sec, acc.currency)
            auto_fee, auto_tax = self._auto_fees(sec, acc, t.kind, gross, gross_sec, cross_fx, t.date)
            fee = t.fee if t.fee != auto_fee else None
            tax = t.tax if t.tax != auto_tax else None
        gross = t.kind == "cash_dividend" and t.tax > 0  # recorded 稅前: edit it the same way
        if gross and sec is not None and acc is not None:
            auto_tax, _ = dividends.dividend_tax(t.amount + t.tax, sec.market, acc.currency)
            tax = t.tax if t.tax != auto_tax else None
        fx = None
        if t.fx_rate is not None and acc is not None:
            on_day = repo.fx_on(self.db, acc.currency, t.date)
            fx = t.fx_rate if on_day is None or on_day[0] != t.fx_rate else None
        if t.balance is not None:
            return format_command("deposit", amount=t.balance, date=t.date, account=acc.name if acc else None,
                                  opening=True, note=t.note)  # fmt: skip
        return format_command(
            t.kind,
            symbol=t.symbol,
            qty=t.qty,
            price=t.price,
            amount=(t.amount + t.tax if gross else abs(t.amount)) if t.kind in ("cash_dividend", "deposit", "withdraw") else None,
            date=t.date,
            account=acc.name if acc else None,
            gross=gross,
            fee=fee,
            tax=tax,
            fx=fx,
            note=t.note,
        )

    def _repay_parts(self, legs: list[Tx]) -> tuple[Account, Account, Decimal, Decimal] | None:
        """(loan, payer, principal, interest) when a transfer group is a 還款, else None."""
        accs = {x.account_id: repo.get_account(self.db, x.account_id) for x in legs}
        loan_leg = next((x for x in legs if x.kind == "transfer" and (a := accs[x.account_id]) and a.type == "loan" and x.amount >= 0), None)
        fee = next((x for x in legs if x.kind == "expense"), None)
        if loan_leg is None or (fee is None and len(legs) > 1):
            return None  # an ordinary transfer (prepaying principal, or the drawdown)
        payer_leg = fee or next((x for x in legs if x is not loan_leg), None)
        loan, payer = accs[loan_leg.account_id], accs[payer_leg.account_id] if payer_leg else None
        if loan is None or payer is None:
            return None
        return loan, payer, loan_leg.amount, -fee.amount if fee else ZERO

    # ── page state ──────────────────────────────────────────────────────

    def state(self) -> dict[str, Any]:
        with self._lock:
            return self._state()

    def _valuation(self) -> dict[str, Any]:
        accounts = repo.list_accounts(self.db, True)
        acc_by_id = {a.id: a for a in accounts}
        txs = repo.list_txs(self.db)
        book = self._replay(txs)
        today = self.today().isoformat()
        secs = repo.securities(self.db, {p.symbol for p in book.positions.values()})
        rates: dict[str, Decimal | None] = {}

        prefer = "cathay" if self.settings()["fx_source"] == "cathay" else "yahoo"

        def rate(cur: str) -> Decimal | None:
            if cur not in rates:
                found = repo.fx_on(self.db, cur, prefer=prefer)
                rates[cur] = found[0] if found else None
            return rates[cur]

        holdings: dict[str, dict[str, Any]] = {}
        acc_value: dict[int, Decimal] = {}
        acc_value_twd: dict[int, Decimal] = {}  # holdings + cash per account, for savings goals
        acc_hold_twd: dict[int, Decimal] = {}  # holdings only, for the 健檢 broker check
        total_return = basis = day_change = ZERO
        missing_fx: set[str] = set()
        for p in book.positions.values():
            acc = acc_by_id[p.account_id]
            sec = secs.get(p.symbol)
            sec_cur = sec.currency if sec else acc.currency
            fx_now = rate(sec_cur)  # values are in the security's currency (differs from the account for 台幣交割)
            if fx_now is None:
                missing_fx.add(sec_cur)
                fx_now = ZERO
            fx_acc = rate(acc.currency) or ZERO
            total_return += p.realized_twd + p.dividends_twd
            basis += p.sold_cost_twd
            h = holdings.setdefault(
                p.symbol,
                {
                    "symbol": p.symbol,
                    "name": sec.name if sec else p.symbol,
                    "market": sec.market if sec else "",
                    "kind": sec.kind if sec else "stock",
                    "currency": sec_cur,
                    "cost_currency": acc.currency,
                    "qty": ZERO, "cost": ZERO, "cost_twd": ZERO, "value": ZERO, "value_twd": ZERO,
                    "unrealized_twd": ZERO, "realized_twd": ZERO, "dividends_twd": ZERO,
                    "day_change_twd": ZERO, "net_twd": ZERO, "tx_ids": [], "accounts": [], "flows": [],
                },
            )  # fmt: skip
            h["realized_twd"] += p.realized_twd
            h["dividends_twd"] += p.dividends_twd
            h["tx_ids"] += p.tx_ids
            h["flows"] += p.flows
            if p.qty == 0:
                continue
            h.setdefault("cost_currencies", set()).add(acc.currency)
            close = sec.last_close if sec else None
            if close is not None:
                value = p.qty * close
            else:  # no quote yet: show at cost
                value = p.cost if sec_cur == acc.currency else (p.cost_twd / fx_now if fx_now else ZERO)
            est_exit = ZERO
            if sec is not None and sec.is_tw and close is not None:
                gross = value.to_integral_value(rounding=ROUND_FLOOR)
                est_exit = fees.tw_fee(gross, *self._fee_terms(acc)) + fees.tw_tax(gross, sec.kind, today)
            unrealized_twd = (value - est_exit) * fx_now - p.cost_twd
            h["qty"] += p.qty
            h["cost"] += p.cost
            h["cost_twd"] += p.cost_twd
            h["value"] += value
            h["value_twd"] += value * fx_now
            h["unrealized_twd"] += unrealized_twd
            h["net_twd"] += (value - est_exit) * fx_now  # what selling would bring, for XIRR
            h["accounts"].append(acc.name)
            acc_hold_twd[p.account_id] = acc_hold_twd.get(p.account_id, ZERO) + value * fx_now
            acc_value[p.account_id] = acc_value.get(p.account_id, ZERO) + (
                value if sec_cur == acc.currency else (value * fx_now / fx_acc if fx_acc else ZERO)
            )
            acc_value_twd[p.account_id] = acc_value_twd.get(p.account_id, ZERO) + value * fx_now
            if sec and close is not None and sec.prev_close is not None:
                h["day_change_twd"] += p.qty * (close - sec.prev_close) * fx_now
            total_return += unrealized_twd
            basis += p.cost_twd
        for h in holdings.values():
            curs = h.pop("cost_currencies", set())
            if len(curs) == 1:
                h["cost_currency"] = curs.pop()
            elif len(curs) > 1:  # the same stock in a TWD (台幣交割) and a foreign account: average cost in TWD
                h["cost"], h["cost_currency"] = h["cost_twd"], "TWD"

        cash_twd: dict[str, Decimal] = {}  # allocation label (台幣現金, 定存, ...) -> TWD
        account_rows = []
        for a in accounts:
            bal = book.cash.get(a.id or 0, ZERO)
            fx_now = rate(a.currency)
            if fx_now is None and bal:
                missing_fx.add(a.currency)
            held_value = acc_value.get(a.id or 0, ZERO)
            if a.type == "deposit":
                label = "定存"
            elif a.type == "credit":
                label = "信用卡"  # normally negative: a liability, shown apart from cash
            elif a.type == "loan":
                label = a.name  # 房貸, 車貸: listed by name under 負債
            else:
                label = f"{fmt.CURRENCY_NAMES.get(a.currency, a.currency)}現金"
            cash_twd[label] = cash_twd.get(label, ZERO) + bal * (fx_now or ZERO)
            acc_value_twd[a.id or 0] = acc_value_twd.get(a.id or 0, ZERO) + bal * (fx_now or ZERO)
            account_rows.append((a, bal, held_value))

        open_h = [h for h in holdings.values() if h["qty"] != 0]
        for h in open_h:
            day_change += h["day_change_twd"]
        total = sum((h["value_twd"] for h in open_h), ZERO) + sum(cash_twd.values(), ZERO)
        # For rebalancing: debts (信用卡, 貸款) are not negative cash, or a mortgage would swamp the mix.
        classes = {"股票": ZERO, "債券": ZERO, "現金": sum((x for x in cash_twd.values() if x > 0), ZERO)}
        for h in open_h:
            classes["債券" if h["kind"] == "bond_etf" else "股票"] += h["value_twd"]
        return {
            "classes": classes,
            "acc_value_twd": acc_value_twd,
            "acc_hold_twd": acc_hold_twd,
            "rate": rate,
            "book": book,
            "holdings": holdings,
            "open": open_h,
            "cash_twd": cash_twd,
            "accounts": account_rows,
            "total": total,
            "day_change": day_change,
            "total_return": total_return,
            "basis": basis,
            "missing_fx": missing_fx,
            "secs": secs,
            "txs": txs,
            "acc_by_id": acc_by_id,
        }

    def _paid_dividends(self, v: dict[str, Any]) -> list[dividends.Paid]:
        """Every cash dividend received, in TWD at the rate on the transaction (or that day's)."""
        out = []
        for t in v["txs"]:
            if t.kind != "cash_dividend" or not t.symbol:
                continue
            acc = v["acc_by_id"].get(t.account_id)
            cur = acc.currency if acc else "TWD"
            if cur == "TWD":
                rate: Decimal | None = Decimal(1)
            elif t.fx_rate is not None:
                rate = t.fx_rate
            else:
                found = repo.fx_on(self.db, cur, t.date)
                rate = found[0] if found else None
            if rate is not None:
                out.append(dividends.Paid(t.date, t.symbol, t.amount * rate))
        return out

    def _dca_summary(
        self, h: dict[str, Any], rules: dict[int, tuple[str, Any]], tx_by_id: dict[int | None, Tx], acc_by_id: dict[int, Account]
    ) -> dict[str, Any] | None:
        """A holding's 定期定額: its rules and the buys they posted (None when it has neither)."""
        mine = [r for sym, r in rules.values() if sym == h["symbol"]]
        buys = [t for i in h["tx_ids"] if (t := tx_by_id.get(i)) and t.kind == "buy" and t.recurring_id in rules]
        if not mine and not buys:
            return None
        invested = ZERO
        for t in buys:
            acc = acc_by_id.get(t.account_id)
            foreign = acc is not None and acc.currency != "TWD"
            invested += -t.amount * (t.fx_rate if foreign and t.fx_rate is not None else Decimal(1))
        qty = sum((t.qty or ZERO for t in buys), ZERO)
        spent = sum(((t.qty or ZERO) * (t.price or ZERO) for t in buys), ZERO)
        today = self.today()
        return {
            "rules": [
                {
                    "id": r.id,
                    "amount": fmt.money(parse(r.line, today).amount, h["cost_currency"]),
                    "freq_label": RECURRING_FREQS[r.freq],
                    "next_date": recurring.next_date(r) if r.active else None,
                    "active": r.active,
                    "error": r.error,
                }
                for r in mine
            ],
            "count": len(buys),
            "first_date": min((t.date for t in buys), default=None),
            "invested": fmt.money(invested) if buys else None,
            "avg_price": fmt.price(spent / qty) if qty > 0 else None,
        }

    def _xirr(self, flows: list[tuple[str, Decimal]], value_now: Decimal) -> float | None:
        """Annualized return of a position's TWD flows plus what selling today would bring.
        None under a year of history: a few months annualized overstates (same rule as the 回測)."""
        if not flows:
            return None
        today = self.today()
        if min(d for d, _ in flows) > (today - timedelta(days=365)).isoformat():
            return None
        dated = [(Date.fromisoformat(d), float(x)) for d, x in flows]
        if value_now:
            dated.append((today, float(value_now)))
        return planner.xirr(dated)

    @staticmethod
    def _asset_classes(v: dict[str, Any]) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        """(investments by class, cash-like by label) in TWD."""
        invest: dict[str, Decimal] = {}
        for h in v["open"]:
            if h["kind"] == "bond_etf":
                label = "債券"
            else:
                label = {"TWSE": "台股", "TPEX": "台股", "US": "美股", "HK": "港股"}.get(h["market"], "海外股")
            invest[label] = invest.get(label, ZERO) + h["value_twd"]
        return invest, dict(v["cash_twd"])

    def _allocation_groups(self, v: dict[str, Any]) -> dict[str, Any]:
        """投資 vs 現金與存款, each with its items; debts (negative balances) listed apart.

        Ratios are shares of everything positive, so every bar in the card uses the same scale.
        """
        invest, cash = self._asset_classes(v)
        debts = {k: x for k, x in cash.items() if x < 0}
        cash = {k: x for k, x in cash.items() if x > 0}
        invest = {k: x for k, x in invest.items() if x > 0}
        positive = sum(invest.values(), ZERO) + sum(cash.values(), ZERO)

        def ratio(x: Decimal) -> float:
            return float(x / positive) if positive else 0.0

        def group(key: str, label: str, items: dict[str, Decimal]) -> dict[str, Any]:
            total = sum(items.values(), ZERO)
            rows = sorted(items.items(), key=lambda kv: kv[1], reverse=True)
            return {
                "key": key,
                "label": label,
                "value": fmt.money(total),
                "ratio": ratio(total),
                "items": [{"label": k, "value": fmt.money(x), "ratio": ratio(x)} for k, x in rows],
            }

        return {
            "groups": [g for g in (group("invest", "投資", invest), group("cash", "現金與存款", cash)) if g["items"]],
            "debts": [{"label": f"{k}欠款" if k == "信用卡" else k, "value": fmt.money(x)} for k, x in sorted(debts.items())],
            "debt_total": fmt.money(sum(debts.values(), ZERO)) if debts else None,
        }

    def _allocation(self, v: dict[str, Any]) -> list[dict[str, Any]]:
        invest, cash = self._asset_classes(v)
        groups = dict(invest)
        for label, amt in cash.items():
            groups[label] = groups.get(label, ZERO) + amt
        items = sorted(((k, x) for k, x in groups.items() if x > 0), key=lambda kv: kv[1], reverse=True)
        if len(items) > MAX_GROUPS:  # the bar has six ink shades; fold the tail into 其他
            tail = sum((x for _, x in items[MAX_GROUPS - 1 :]), ZERO)
            items = [*items[: MAX_GROUPS - 1], ("其他", tail)]
        positive = sum((x for _, x in items), ZERO)
        return [{"label": k, "value": fmt.money(x), "ratio": float(x / positive) if positive else 0.0} for k, x in items]

    def _state(self) -> dict[str, Any]:
        v = self._valuation()
        settings = self.settings()
        acc_by_id = v["acc_by_id"]

        ttm_start = dividends.ttm_start(self.today())
        ttm_by: dict[str, Decimal] = {}
        for d in self._paid_dividends(v):
            if d.date > ttm_start:
                ttm_by[d.symbol] = ttm_by.get(d.symbol, ZERO) + d.twd
        dca_rules = recurring.dca_rules(self)
        tx_by_id = {t.id: t for t in v["txs"]}
        holdings = []
        for h in sorted(v["open"], key=lambda h: h["value_twd"], reverse=True):
            sec = v["secs"].get(h["symbol"])
            cur = h["currency"]
            ttm = ttm_by.get(h["symbol"], ZERO)
            rate = self._xirr(h["flows"], h["net_twd"])
            holdings.append(
                {
                    "symbol": h["symbol"],
                    "name": h["name"],
                    "currency": cur,
                    "qty": fmt.qty(h["qty"]),
                    "avg_cost": fmt.price(h["cost"] / h["qty"]),
                    "cost_currency": h["cost_currency"],  # differs from currency for 台幣交割 holdings
                    "close": fmt.price(sec.last_close) if sec else None,
                    "close_date": sec.last_date if sec else None,
                    "value": fmt.money(h["value"], cur),
                    "value_twd": fmt.money(h["value_twd"]),
                    "unrealized": fmt.money(h["unrealized_twd"], signed=True),
                    "unrealized_pct": fmt.pct(h["unrealized_twd"], h["cost_twd"]),
                    "realized": fmt.money(h["realized_twd"], signed=True) if h["realized_twd"] else None,
                    "dividends": fmt.money(h["dividends_twd"]) if h["dividends_twd"] else None,
                    "dividends_ttm": fmt.money(ttm) if ttm else None,
                    "yield_on_cost": fmt.pct(ttm, h["cost_twd"]) if ttm and h["cost_twd"] > 0 else None,
                    "xirr": _annual(rate),
                    "day_change": fmt.money(h["day_change_twd"], signed=True),
                    "day_pct": fmt.pct(sec.last_close - sec.prev_close, sec.prev_close)
                    if sec and sec.last_close is not None and sec.prev_close
                    else None,
                    "sign": fmt.sign(h["unrealized_twd"]),
                    "day_sign": fmt.sign(h["day_change_twd"]),
                    "weight": float(h["value_twd"] / v["total"]) if v["total"] > 0 else 0.0,
                    "accounts": sorted(set(h["accounts"])),
                    "tx_ids": h["tx_ids"],
                    "dca": self._dca_summary(h, dca_rules, tx_by_id, acc_by_id),
                }
            )

        closed = [
            {
                "symbol": h["symbol"],
                "name": h["name"],
                "realized": fmt.money(h["realized_twd"], signed=True),
                "dividends": fmt.money(h["dividends_twd"]) if h["dividends_twd"] else None,
                "sign": fmt.sign(h["realized_twd"] + h["dividends_twd"]),
                "tx_ids": h["tx_ids"],
            }
            for h in v["holdings"].values()
            if h["qty"] == 0
        ]

        cats = {c.id: c.name for c in repo.list_categories(self.db)}
        legs: dict[str, list[Tx]] = {}
        for t in v["txs"]:
            if t.transfer_group:
                legs.setdefault(t.transfer_group, []).append(t)
        repays = {g: r for g, rows in legs.items() if any(x.kind == "expense" for x in rows) and (r := self._repay_parts(rows))}
        txs = []
        for t in reversed(v["txs"]):
            acc = acc_by_id.get(t.account_id)
            sec = v["secs"].get(t.symbol) if t.symbol else None
            cur = acc.currency if acc else "TWD"
            to_name = received = None
            if t.transfer_group in repays:
                if t.kind != "expense":
                    continue  # a 還款 is listed once, on its interest row
                loan, payer, principal, interest = repays[t.transfer_group]
                paid = principal + interest
                note = f"本金 {fmt.money(principal, cur)}・利息 {fmt.money(interest, cur)}" + (f"・{t.note}" if t.note else "")
                txs.append(
                    {
                        "category": None, "to_account": loan.name, "received": None,
                        "twd": fmt.money(paid * (t.fx_rate or Decimal(1))), "value": float(paid * (t.fx_rate or Decimal(1))),
                        "id": t.id, "date": t.date, "kind": "repay", "label": TX_KINDS["repay"], "symbol": None,
                        "name": None, "qty": None, "ratio": None, "price": None,
                        "amount": fmt.money(-paid, cur, signed=True), "sign": -1, "currency": cur,
                        "account": payer.name, "note": note, "recurring": t.recurring_id is not None,
                    }
                )  # fmt: skip
                continue
            if t.kind == "transfer" and t.transfer_group:
                if t.amount >= 0:
                    continue  # shown once, on the outgoing leg
                inn = next((x for x in legs[t.transfer_group] if x.amount >= 0), None)
                if inn is not None:
                    to_acc = acc_by_id.get(inn.account_id)
                    to_name = to_acc.name if to_acc else ""
                    if to_acc and to_acc.currency != cur:
                        received = f"{fmt.money(inn.amount, to_acc.currency)} {to_acc.currency}"
            txs.append(
                {
                    "category": cats.get(t.category_id) if t.category_id else None,
                    "to_account": to_name,
                    "received": received,
                    "twd": fmt.money(abs(t.amount) * (t.fx_rate or Decimal(1))) if t.kind in CATEGORY_KINDS else None,
                    "id": t.id,
                    "date": t.date,
                    "kind": t.kind,
                    "label": ("期初欠款" if t.balance < 0 else "期初餘額") if t.balance is not None else TX_KINDS.get(t.kind, t.kind),
                    "symbol": t.symbol,
                    "name": sec.name if sec else None,
                    "qty": fmt.qty(t.qty) if t.kind != "split" else None,
                    "ratio": fmt.qty(t.qty) if t.kind == "split" else None,
                    "price": fmt.price(t.price),
                    "amount": fmt.money(t.balance, cur) if t.balance is not None
                    else fmt.money(t.amount, cur, signed=True) if t.amount else None,
                    "sign": fmt.sign(t.amount),
                    "currency": cur,
                    "account": acc.name if acc else "",
                    "note": t.note,
                    "value": float(abs(t.amount) * (t.fx_rate if t.fx_rate is not None and cur != "TWD" else Decimal(1))),
                    "recurring": t.recurring_id is not None,
                    "dca": t.recurring_id in dca_rules,
                }
            )

        autopay = self.autopay_accounts()
        accounts = [
            {
                "id": a.id,
                "name": a.name,
                "type": a.type,
                "type_label": ACCOUNT_TYPES.get(a.type, a.type),
                "currency": a.currency,
                "cash": fmt.money(bal, a.currency),
                "cash_sign": fmt.sign(bal),
                "holdings": fmt.money(held, a.currency) if held else None,
                "fee_discount": str(a.fee_discount) if a.fee_discount is not None else None,
                "fee_min": str(a.fee_min) if a.fee_min is not None else None,
                "group_name": a.group_name,
                "value_twd": fmt.money(v["acc_value_twd"].get(a.id or 0, ZERO)),
                "rate": str(a.rate) if a.rate is not None else None,
                "start_date": a.start_date,
                "maturity_date": a.maturity_date,
                "principal": str(a.principal) if a.principal is not None else None,
                "term_years": str(a.term_years) if a.term_years is not None else None,
                "grace_years": str(a.grace_years) if a.grace_years is not None else None,
                "statement_day": a.statement_day,
                "pay_day": a.pay_day,
                "autopay": autopay.get(a.id or 0),
                "archived": a.archived,
                "color": a.color,
            }
            for a, bal, held in v["accounts"]
        ]

        quote_dates = sorted({s.last_date for s in v["secs"].values() if s.last_date})
        return {
            "total": fmt.money(v["total"]),
            "day_change": fmt.money(v["day_change"], signed=True),
            "day_change_pct": fmt.pct(v["day_change"], v["total"] - v["day_change"]),
            "day_sign": fmt.sign(v["day_change"]),
            "total_return": fmt.money(v["total_return"], signed=True),
            "total_return_pct": fmt.pct(v["total_return"], v["basis"]),
            "return_sign": fmt.sign(v["total_return"]),
            "xirr": _annual(
                self._xirr(
                    [f for h in v["holdings"].values() for f in h["flows"]], sum((h["net_twd"] for h in v["open"]), ZERO)
                )
            ),
            "allocation": self._allocation(v),
            "allocation_groups": self._allocation_groups(v),
            "history": [
                {"date": d, "total": str(x), "holdings": _snapshot_holdings(b)} for d, x, b in repo.list_snapshot_breakdowns(self.db)
            ],
            "holdings": holdings,
            "holdings_value": fmt.money(sum((h["value_twd"] for h in v["open"]), ZERO)),
            "holdings_unrealized": fmt.money(sum((h["unrealized_twd"] for h in v["open"]), ZERO), signed=True),
            "holdings_unrealized_sign": fmt.sign(sum((h["unrealized_twd"] for h in v["open"]), ZERO)),
            "holdings_unrealized_pct": fmt.pct(
                sum((h["unrealized_twd"] for h in v["open"]), ZERO), sum((h["cost_twd"] for h in v["open"]), ZERO)
            ),
            "closed": closed,
            "transactions": txs,
            "categories": self._categories(v["txs"]),
            "account_groups": self._groups(v),
            "deposits": self._deposits(v),
            "loans": self._loans(v),
            "fx_positions": self._fx_positions(v),
            "accounts": accounts,
            "account_types": ACCOUNT_TYPES,
            "currencies": fmt.CURRENCY_NAMES,
            "settings": settings,
            "missing_fx": sorted(v["missing_fx"]),
            "quotes": {
                "latest": quote_dates[-1] if quote_dates else None,
                "oldest": quote_dates[0] if quote_dates else None,
                "refreshed_at": self.status["refreshed_at"],
                "running": self.status["running"],
                "errors": self.status["errors"],
                "tw_listed": repo.count_tw_securities(self.db),
                "fx_source": settings["fx_source"],
            },
            "today": self.today().isoformat(),
        }

    def _categories(self, txs: list[Tx]) -> list[dict[str, Any]]:
        """Income/expense categories, most used in the last 90 days first (the composer's chips)."""
        since = (self.today() - timedelta(days=90)).isoformat()
        uses: dict[int, int] = {}
        for t in txs:
            if t.category_id and t.date >= since:
                uses[t.category_id] = uses.get(t.category_id, 0) + 1
        cats = [c for c in repo.list_categories(self.db) if not c.archived]
        cats.sort(key=lambda c: (-uses.get(c.id or 0, 0), c.sort, c.id or 0))
        count = repo.category_use_counts(self.db)  # all time, for 管理分類
        return [
            {"id": c.id, "name": c.name, "kind": c.kind, "uses": uses.get(c.id or 0, 0), "parent_id": c.parent_id,
             "sort": c.sort, "count": count.get(c.id or 0, 0)}
            for c in cats
        ]  # fmt: skip

    def tx_fields(self, tx_id: int) -> dict[str, Any]:
        """A stored transaction as the composer's fields (via its command line, so both stay in sync)."""
        line = self.tx_line(tx_id)
        cmd = parse(line, self.today())
        backfill = cmd.action == "holding_in"
        kind = "buy" if backfill else cmd.action if cmd.action in COMPOSER_KINDS else "more"

        def plain(d: Decimal | None) -> str:
            return "" if d is None else format(d.normalize(), "f")

        return {
            "kind": kind,
            "more": cmd.action if kind == "more" else "deposit",
            "amount": plain(cmd.amount),
            "category": cmd.category or "",
            "account": cmd.account or "",
            "to_account": cmd.to_account or "",
            "symbol": cmd.symbol or "",
            "qty": plain(cmd.qty),
            "price": plain(cmd.price),
            "fee": plain(cmd.fee),
            "tax": plain(cmd.tax),
            "fx": plain(cmd.fx),
            "total": plain(cmd.total),
            "interest": plain(cmd.interest),
            "opening": cmd.opening,
            "gross": cmd.gross,
            "date": cmd.date or self.today().isoformat(),
            "note": cmd.note,
            "backfill": backfill,
            "line": line,
        }

    def _groups(self, v: dict[str, Any]) -> list[dict[str, Any]]:
        """Multi-currency accounts as one row each: currencies held and the TWD total."""
        groups: dict[str, dict[str, Any]] = {}
        for a, _, _ in v["accounts"]:
            if not a.group_name:
                continue
            g = groups.setdefault(a.group_name, {"name": a.group_name, "type": a.type, "color": a.color, "currencies": [], "total": ZERO})
            if not a.archived:
                g["currencies"].append(a.currency)
            g["total"] += v["acc_value_twd"].get(a.id or 0, ZERO)
        return [{**g, "total": fmt.money(g["total"]), "archived": not g["currencies"]} for g in groups.values()]

    def _deposits(self, v: dict[str, Any]) -> list[dict[str, Any]]:
        """Time deposits with simple-interest accrual to today; soonest maturity first."""
        today = self.today()
        out = []
        for a, bal, _ in v["accounts"]:
            if a.type != "deposit" or a.archived or not bal:
                continue
            accrued = ZERO
            if a.rate and a.start_date:
                start = Date.fromisoformat(a.start_date)
                end = min(today, Date.fromisoformat(a.maturity_date)) if a.maturity_date else today
                days = max(0, (end - start).days)
                accrued = bal * a.rate / 100 * days / 365
            days_left = (Date.fromisoformat(a.maturity_date) - today).days if a.maturity_date else None
            out.append(
                {
                    "id": a.id,
                    "name": a.name,
                    "currency": a.currency,
                    "principal": fmt.money(bal, a.currency),
                    "rate": f"{a.rate.normalize():f}%" if a.rate is not None else None,
                    "start_date": a.start_date,
                    "maturity_date": a.maturity_date,
                    "days_left": days_left,
                    "matured": days_left is not None and days_left <= 0,
                    "soon": days_left is not None and 0 < days_left <= 30,
                    "accrued": fmt.money(accrued, a.currency) if accrued else None,
                }
            )
        out.sort(key=lambda d: (d["days_left"] is None, d["days_left"] or 0))
        return out

    def loan_payments(self) -> list[tuple[str, Decimal]]:
        """(name, this month's scheduled payment) for every loan still owed, for the health check."""
        today = self.today().isoformat()
        out = []
        for a in repo.list_accounts(self.db):
            if a.type == "loan" and self._owed(a, today, set()) > 0 and (pay := self._scheduled_payment(a, today)):
                out.append((a.name, pay * (self._rate(a, today, None) or Decimal(1))))
        return out

    def _loans(self, v: dict[str, Any]) -> list[dict[str, Any]]:
        """Loan accounts: what is owed, share repaid, this month's payment and when it would be paid off."""
        today = self.today()
        out = []
        for a, bal, _ in v["accounts"]:
            if a.type != "loan" or a.archived:
                continue
            owed, cur = -bal, a.currency
            sched = self._schedule(a)
            payment = self._scheduled_payment(a, today.isoformat())
            left = None
            if sched is not None and owed > 0:
                left = planner.payoff(float(owed), float(a.rate or 0) / 100, sched, self._period(a, today.isoformat()))
            out.append(
                {
                    "id": a.id,
                    "name": a.name,
                    "currency": cur,
                    "owed": fmt.money(max(owed, ZERO), cur),
                    "principal": fmt.money(a.principal, cur) if a.principal else None,
                    "ratio": float(min(1, max(0, 1 - owed / a.principal))) if a.principal else None,
                    "rate": f"{a.rate.normalize():f}%" if a.rate is not None else None,
                    "payment": fmt.money(payment, cur) if payment and owed > 0 else None,
                    "payoff": planner.shift_month(today.isoformat()[:7], left[0] - 1) if left else None,
                    "months_left": left[0] if left else None,
                    "interest_left": fmt.money(Decimal(str(round(left[1]))), cur) if left else None,
                    "done": owed <= 0,
                }
            )
        return out

    def _fx_positions(self, v: dict[str, Any]) -> list[dict[str, Any]]:
        """Foreign cash per currency: balance, average cost rate, today's rate and the FX gain."""
        book: Book = v["book"]
        per: dict[str, list[Decimal]] = {}
        for a, bal, _ in v["accounts"]:
            if a.currency == "TWD" or not bal:
                continue
            row = per.setdefault(a.currency, [ZERO, ZERO])
            row[0] += bal
            row[1] += book.cash_cost_twd.get(a.id or 0, ZERO)
        out = []
        for cur, (bal, cost) in sorted(per.items()):
            now = v["rate"](cur)
            value = bal * now if now is not None else None
            out.append(
                {
                    "currency": cur,
                    "name": fmt.CURRENCY_NAMES.get(cur, cur),
                    "balance": fmt.money(bal, cur),
                    "avg_rate": f"{(cost / bal).quantize(Decimal('0.0001')).normalize():f}" if bal > 0 and cost else None,
                    "rate": str(now) if now is not None else None,
                    "value_twd": fmt.money(value) if value is not None else None,
                    "gain": fmt.money(value - cost, signed=True) if value is not None and bal > 0 and cost else None,
                    "sign": fmt.sign(value - cost) if value is not None and bal > 0 and cost else 0,
                }
            )
        return out

    def snapshot(self) -> None:
        """Store today's net worth; rewritten on every change and refresh."""
        v = self._valuation()
        if not v["txs"]:
            return
        breakdown = {g["label"]: g["value"] for g in self._allocation(v)}
        breakdown[HOLDINGS_KEY] = str(sum((h["value_twd"] for h in v["open"]), ZERO))
        repo.put_snapshot(self.db, self.today().isoformat(), v["total"], breakdown)

    # ── quotes ──────────────────────────────────────────────────────────

    def refresh(self, tw: bool = True, us: bool = True) -> None:
        """Fetch quotes and FX for everything held. Errors are collected, never raised."""
        with self._lock:
            if self.status["running"]:
                return
            self.status["running"] = True
        errors: list[str] = []
        try:
            book = self._replay(repo.list_txs(self.db))
            held = {p.symbol for p in book.open_positions()} | set(repo.list_watchlist(self.db))  # and the 自選股
            known = repo.securities(self.db, held)
            if tw:
                try:
                    secs = twse.fetch_all(self.client)
                    repo.upsert_securities(self.db, secs)
                    repo.put_prices(
                        self.db,
                        [(s.symbol, s.last_date, s.last_close) for s in secs if s.symbol in held and s.last_date and s.last_close is not None],
                    )
                    # The exchange feed is one day only: fill a month from Yahoo for the 一週 change, once.
                    tw_known = repo.securities(self.db, held)
                    self.backfill_prices([x for x in tw_known.values() if x.is_tw and not self._has_week(x)])
                except ProviderError as e:
                    log.warning("%s", e)
                    errors.append(str(e))
                try:
                    repo.put_dividend_events(self.db, [(s, d, c, None) for s, d, c in twse.fetch_ex_dividends(self.client)])
                    repo.put_valuations(self.db, twse.fetch_valuations(self.client))
                except ProviderError as e:
                    log.warning("%s", e)
                    errors.append(str(e))
                # 上櫃 has no 除權息預告 feed: FinMind's dividend table, for what is held or watched.
                since = (self.today() - timedelta(days=400)).isoformat()
                for sec in repo.securities(self.db, held).values():
                    if sec.market != "TPEX":
                        continue
                    try:
                        repo.put_dividend_events(self.db, [(sec.symbol, d, c, pay) for d, c, pay in finmind.dividends(self.client, sec.symbol, since)])
                    except ProviderError as e:
                        log.info("%s", e)
            if us:
                for sym in sorted(s for s in held if (sec := known.get(s)) is not None and not sec.is_tw):
                    try:
                        h = yahoo.chart(self.client, sym, "1mo")  # a month, for the 一週 change
                    except ProviderError as e:
                        log.warning("%s", e)
                        errors.append(str(e))
                        continue
                    sec = known[sym]
                    if h.last:
                        sec.last_date, sec.last_close = h.last
                        sec.prev_close = h.prev_close
                        repo.upsert_securities(self.db, [sec])
                    repo.put_prices(self.db, [(sym, d, c) for d, c in h.closes])
            currencies = ({a.currency for a in repo.list_accounts(self.db, True)} | {s.currency for s in known.values()}) - {"TWD"}
            for cur in sorted(currencies):
                try:
                    h = yahoo.chart(self.client, yahoo.fx_symbol(cur))
                    repo.put_fx(self.db, [(cur, d, r) for d, r in h.closes])
                except ProviderError as e:
                    log.warning("%s", e)
                    errors.append(f"{cur} 匯率：{e}")
            if currencies and self.settings()["fx_source"] == "cathay":
                try:
                    day, board = cathay.fetch_board(self.client if self.client_is_mock else None)
                    repo.put_board_fx(
                        self.db, "cathay", [(c, day, board[c].buy, board[c].sell) for c in currencies if c in board]
                    )
                    missing = sorted(currencies - board.keys())
                    if missing:
                        log.info("國泰牌告沒有 %s，改用市場匯率", "、".join(missing))
                except ProviderError as e:
                    log.warning("%s", e)
                    errors.append(f"{e}（暫時改用市場匯率）")
            self.snapshot()
        except Exception as e:  # never let the poller thread die
            log.exception("refresh failed")
            errors.append(f"更新失敗：{e}")
        finally:
            with self._lock:
                self.status = {
                    "refreshed_at": taipei_now().isoformat(timespec="seconds"),
                    "errors": errors,
                    "running": False,
                }

    def _has_week(self, sec: Security) -> bool:
        if not sec.last_date:
            return True  # nothing to compare with anyway
        start = (Date.fromisoformat(sec.last_date) - timedelta(days=21)).isoformat()
        return len(repo.closes_from(self.db, sec.symbol, start)) > 5

    def backfill_prices(self, secs: list[Security]) -> None:
        """A month of daily closes from Yahoo (2330.TW / 6488.TWO for Taiwan). Taiwan days after the
        exchange's latest close are dropped: Yahoo's bar for today may be intraday."""
        for sec in secs:
            ysym = f"{sec.symbol}.TW" if sec.market == "TWSE" else f"{sec.symbol}.TWO" if sec.market == "TPEX" else sec.symbol
            try:
                h = yahoo.chart(self.client, ysym, "1mo")
            except ProviderError as e:
                log.info("%s", e)  # only the 一週 change is missing; not worth a footer error
                continue
            rows = [(sec.symbol, d, c) for d, c in h.closes if not sec.is_tw or (sec.last_date and d <= sec.last_date)]
            repo.put_prices(self.db, rows)

    # ── export ──────────────────────────────────────────────────────────

    def export_csv(self, dest: Path) -> Path:
        accounts = {a.id: a for a in repo.list_accounts(self.db, True)}
        secs = repo.securities(self.db, {t.symbol for t in repo.list_txs(self.db) if t.symbol})
        with dest.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel reads Chinese
            w = csv.writer(f)
            w.writerow(["日期", "帳戶", "幣別", "類型", "代號", "名稱", "股數", "價格", "手續費", "稅", "金額", "匯率", "備註"])
            for t in repo.list_txs(self.db):
                a = accounts.get(t.account_id)
                s = secs.get(t.symbol) if t.symbol else None
                w.writerow([
                    t.date, a.name if a else "", a.currency if a else "", TX_KINDS.get(t.kind, t.kind),
                    t.symbol or "", s.name if s else "", t.qty if t.qty is not None else "",
                    t.price if t.price is not None else "", t.fee, t.tax, t.amount,
                    t.fx_rate if t.fx_rate is not None else "", t.note,
                ])  # fmt: skip
        return dest


def _snapshot_holdings(breakdown: dict[str, Any]) -> str | None:
    """Holdings value on a snapshot day. Older snapshots lack the key: sum their investment classes,
    unless the tail was folded into 其他 (then the split is unknown)."""
    if HOLDINGS_KEY in breakdown:
        return str(breakdown[HOLDINGS_KEY])
    if "其他" in breakdown:
        return None
    return str(sum((Decimal(str(x).replace(",", "")) for k, x in breakdown.items() if k in INVEST_LABELS), ZERO))


def _annual(rate: float | None) -> str | None:
    """'+8.2%' for an annualized return."""
    if rate is None:
        return None
    return fmt.pct(Decimal(str(round(rate, 6))), Decimal(1))


def _positive(v: object, label: str, allow_zero: bool = False) -> Decimal:
    try:
        d = Decimal(str(v).strip())
    except Exception:
        raise EntryError(f"{label}要是數字") from None
    if not d.is_finite() or d < 0 or (d == 0 and not allow_zero):
        raise EntryError(f"{label}要是正數")
    return d


def _optional_positive(v: object, label: str) -> Decimal | None:
    if v is None or str(v).strip() == "":
        return None
    return _positive(v, label, allow_zero=True)


def _optional_day(v: object, label: str) -> int | None:
    """A day of month, 1–31."""
    if v is None or str(v).strip() == "":
        return None
    try:
        day = int(str(v).strip().removesuffix("號").removesuffix("日"))
    except ValueError:
        raise EntryError(f"{label}要填 1 到 31 的數字") from None
    if not 1 <= day <= 31:
        raise EntryError(f"{label}要填 1 到 31 的數字")
    return day


def _optional_date(v: object, label: str) -> str | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return Date.fromisoformat(str(v).strip()).isoformat()
    except ValueError:
        raise EntryError(f"{label}要是 YYYY-MM-DD 格式") from None
