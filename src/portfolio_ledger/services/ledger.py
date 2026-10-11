"""The app's use cases: preview/commit a command line, build the page state, refresh quotes.

api.py is a thin wrapper around this; poller.py calls refresh(). Thread-safety comes from Db's lock
plus self._lock around the multi-step operations.
"""

from __future__ import annotations

import csv
import logging
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .. import repo
from ..db import Db
from ..models import ACCOUNT_TYPES, SPENDING_TYPES, TX_KINDS, Account, Category, Security, Tx
from ..providers import cathay, twse, yahoo
from ..providers.base import ProviderError, make_client
from . import fees, fmt
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
BROKER_TYPES = ("broker_tw", "broker_us")
ZERO = Decimal(0)
MAX_GROUPS = 6
log = logging.getLogger(__name__)


class EntryError(ValueError):
    pass


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

    # ── settings ────────────────────────────────────────────────────────

    def settings(self) -> dict[str, str]:
        return {
            "fee_discount": repo.get_setting(self.db, "fee_discount", str(fees.DEFAULT_DISCOUNT)),
            "fee_min": repo.get_setting(self.db, "fee_min", str(fees.DEFAULT_MIN_FEE)),
            "privacy": repo.get_setting(self.db, "privacy", "0"),
            "up_color": repo.get_setting(self.db, "up_color", "red"),  # Taiwan: red is up
            # Foreign cash valuation: 'cathay' = 國泰世華 即期買進 (like the 國泰 app), 'market' = Yahoo mid-rate.
            "fx_source": repo.get_setting(self.db, "fx_source", "market"),
        }

    def save_settings(self, values: dict[str, str]) -> None:
        for key in ("fee_discount", "fee_min"):
            if key in values:
                d = _positive(values[key], "手續費折扣" if key == "fee_discount" else "最低手續費", allow_zero=True)
                repo.set_setting(self.db, key, str(d))
        for key, allowed in (("privacy", {"0", "1"}), ("up_color", {"red", "green"}), ("fx_source", {"cathay", "market"})):
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

    def save_group(self, data: dict[str, Any]) -> None:
        """Create or update a multi-currency account: one part per currency, named "{name}-{CUR}".

        Removing a currency deletes its part, or archives it when it already has transactions.
        """
        name = self._valid_name(data.get("name"))
        old = str(data.get("old_name") or "").strip() or None
        type_ = data.get("type") or "bank"
        if type_ not in ("bank", "cash", "broker_us"):
            raise EntryError("多幣別帳戶只能是銀行、現金或複委託")
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
        for a in parts:  # rename / restore / retire existing parts
            a.name, a.group_name, a.type = f"{name}-{a.currency}", name, type_
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
                repo.save_account(self.db, Account(None, f"{name}-{c}", type_, c, group_name=name))

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
        )
        if type_ == "deposit":
            acc.rate = _optional_positive(data.get("rate"), "年利率")
            acc.start_date = _optional_date(data.get("start_date"), "起存日")
            acc.maturity_date = _optional_date(data.get("maturity_date"), "到期日")
            if acc.start_date and acc.maturity_date and acc.maturity_date <= acc.start_date:
                raise EntryError("到期日要在起存日之後")
        return repo.save_account(self.db, acc)

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

    def build(self, cmd: Command, edit_id: int | None = None) -> Draft:
        """Resolve a parsed command into ready-to-save transactions, or raise EntryError."""
        if cmd.missing:
            raise EntryError("還缺：" + "、".join(FIELD_NAMES[m] for m in cmd.missing))
        today = self.today().isoformat()
        day = cmd.date or today
        if day > today:
            raise EntryError("日期不能在未來")
        skip = self._edit_ids(edit_id)
        keep_id = edit_id if len(skip) == 1 and cmd.action != "transfer" else None
        if cmd.action == "transfer":
            draft = self._build_transfer(cmd, day)
        elif cmd.action in CATEGORY_KINDS:
            draft = self._build_flow(cmd, day, keep_id)
        else:
            draft = self._build_trade(cmd, day, keep_id)
        self._check(draft.txs, skip)
        return draft

    def _build_flow(self, cmd: Command, day: str, keep_id: int | None) -> Draft:
        assert cmd.amount is not None
        acc = self._pick_account(cmd, None)
        cat, cat_name = self._resolve_category(cmd.category, cmd.action)
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
        return Draft([tx], acc, category=cat_name, new_category=None if cat else cat_name)

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
        elif cmd.action in ("stock_dividend", "split"):
            qty = cmd.qty
            amount = ZERO
        elif cmd.action == "deposit":
            assert cmd.amount is not None
            amount = cmd.amount
        else:  # withdraw
            assert cmd.amount is not None
            amount = -cmd.amount

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
        except EntryError as e:
            return {"status": "error", "message": str(e)}
        return {"status": "ready", **self._describe(draft)}

    def _describe(self, d: Draft) -> dict[str, Any]:
        t, cur = d.tx, d.account.currency
        parts: list[str] = []
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
        if t.kind in CATEGORY_KINDS:
            title = f"{TX_KINDS[t.kind]} {d.category}"
            if d.new_category:
                parts.append("新分類")
            parts.append(d.account.name)
        else:
            name = f"{d.security.name} {d.security.symbol}" if d.security else d.account.name
            title = f"{TX_KINDS[t.kind]} {name}"
        if t.kind in ("buy", "sell", "holding_in"):
            parts.append(f"{fmt.qty(t.qty)} 股 @ {fmt.price(t.price)}")
        elif t.kind == "stock_dividend":
            parts.append(f"配 {fmt.qty(t.qty)} 股")
        elif t.kind == "split":
            parts.append(f"1 股變 {fmt.qty(t.qty)} 股")
        if t.fee:
            parts.append(f"手續費 {fmt.money(t.fee, cur)}")
        if t.tax:
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

    def commit(self, text: str, edit_id: int | None = None) -> int:
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
                draft.tx.category_id = repo.add_category(self.db, draft.new_category, draft.tx.kind)
            if len(draft.txs) == 1 and draft.tx.id is not None:
                tx_id = repo.save_tx(self.db, draft.tx)  # plain edit keeps its id (and same-day order)
            else:
                tx_id = repo.replace_txs(self.db, sorted(skip), draft.txs)[0]
            self.snapshot()
            return tx_id

    def delete(self, tx_id: int) -> None:
        with self._lock:
            ids = self._edit_ids(tx_id)
            self._check([], ids)
            repo.replace_txs(self.db, sorted(ids), [])
            self.snapshot()

    def tx_line(self, tx_id: int) -> str:
        """The command line that recreates a stored transaction, for editing in place."""
        t = repo.get_tx(self.db, tx_id)
        if t is None:
            raise EntryError("這筆交易已經不存在")
        acc = repo.get_account(self.db, t.account_id)
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
        fx = None
        if t.fx_rate is not None and acc is not None:
            on_day = repo.fx_on(self.db, acc.currency, t.date)
            fx = t.fx_rate if on_day is None or on_day[0] != t.fx_rate else None
        return format_command(
            t.kind,
            symbol=t.symbol,
            qty=t.qty,
            price=t.price,
            amount=abs(t.amount) if t.kind in ("cash_dividend", "deposit", "withdraw") else None,
            date=t.date,
            account=acc.name if acc else None,
            fee=fee,
            tax=tax,
            fx=fx,
            note=t.note,
        )

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
                    "day_change_twd": ZERO, "tx_ids": [], "accounts": [],
                },
            )  # fmt: skip
            h["realized_twd"] += p.realized_twd
            h["dividends_twd"] += p.dividends_twd
            h["tx_ids"] += p.tx_ids
            if p.qty == 0:
                continue
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
            h["accounts"].append(acc.name)
            acc_value[p.account_id] = acc_value.get(p.account_id, ZERO) + (
                value if sec_cur == acc.currency else (value * fx_now / fx_acc if fx_acc else ZERO)
            )
            acc_value_twd[p.account_id] = acc_value_twd.get(p.account_id, ZERO) + value * fx_now
            if sec and close is not None and sec.prev_close is not None:
                h["day_change_twd"] += p.qty * (close - sec.prev_close) * fx_now
            total_return += unrealized_twd
            basis += p.cost_twd

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
            else:
                label = f"{fmt.CURRENCY_NAMES.get(a.currency, a.currency)}現金"
            cash_twd[label] = cash_twd.get(label, ZERO) + bal * (fx_now or ZERO)
            acc_value_twd[a.id or 0] = acc_value_twd.get(a.id or 0, ZERO) + bal * (fx_now or ZERO)
            account_rows.append((a, bal, held_value))

        open_h = [h for h in holdings.values() if h["qty"] != 0]
        for h in open_h:
            day_change += h["day_change_twd"]
        total = sum((h["value_twd"] for h in open_h), ZERO) + sum(cash_twd.values(), ZERO)
        classes = {"股票": ZERO, "債券": ZERO, "現金": sum(cash_twd.values(), ZERO)}  # for rebalancing
        for h in open_h:
            classes["債券" if h["kind"] == "bond_etf" else "股票"] += h["value_twd"]
        return {
            "classes": classes,
            "acc_value_twd": acc_value_twd,
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

        holdings = []
        for h in sorted(v["open"], key=lambda h: h["value_twd"], reverse=True):
            sec = v["secs"].get(h["symbol"])
            cur = h["currency"]
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
                    "day_change": fmt.money(h["day_change_twd"], signed=True),
                    "day_pct": fmt.pct(sec.last_close - sec.prev_close, sec.prev_close)
                    if sec and sec.last_close is not None and sec.prev_close
                    else None,
                    "sign": fmt.sign(h["unrealized_twd"]),
                    "day_sign": fmt.sign(h["day_change_twd"]),
                    "weight": float(h["value_twd"] / v["total"]) if v["total"] > 0 else 0.0,
                    "accounts": sorted(set(h["accounts"])),
                    "tx_ids": h["tx_ids"],
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
        txs = []
        for t in reversed(v["txs"]):
            acc = acc_by_id.get(t.account_id)
            sec = v["secs"].get(t.symbol) if t.symbol else None
            cur = acc.currency if acc else "TWD"
            to_name = received = None
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
                    "label": TX_KINDS.get(t.kind, t.kind),
                    "symbol": t.symbol,
                    "name": sec.name if sec else None,
                    "qty": fmt.qty(t.qty) if t.kind != "split" else None,
                    "ratio": fmt.qty(t.qty) if t.kind == "split" else None,
                    "price": fmt.price(t.price),
                    "amount": fmt.money(t.amount, cur, signed=True) if t.amount else None,
                    "sign": fmt.sign(t.amount),
                    "currency": cur,
                    "account": acc.name if acc else "",
                    "note": t.note,
                }
            )

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
                "archived": a.archived,
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
            "allocation": self._allocation(v),
            "allocation_groups": self._allocation_groups(v),
            "history": [{"date": d, "total": str(x)} for d, x in repo.list_snapshots(self.db)],
            "holdings": holdings,
            "holdings_value": fmt.money(sum((h["value_twd"] for h in v["open"]), ZERO)),
            "holdings_unrealized": fmt.money(sum((h["unrealized_twd"] for h in v["open"]), ZERO), signed=True),
            "holdings_unrealized_sign": fmt.sign(sum((h["unrealized_twd"] for h in v["open"]), ZERO)),
            "closed": closed,
            "transactions": txs,
            "categories": self._categories(v["txs"]),
            "account_groups": self._groups(v),
            "deposits": self._deposits(v),
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
        return [{"id": c.id, "name": c.name, "kind": c.kind, "uses": uses.get(c.id or 0, 0)} for c in cats]

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
            g = groups.setdefault(a.group_name, {"name": a.group_name, "type": a.type, "currencies": [], "total": ZERO})
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
            held = {p.symbol for p in book.open_positions()}
            known = repo.securities(self.db, held)
            if tw:
                try:
                    secs = twse.fetch_all(self.client)
                    repo.upsert_securities(self.db, secs)
                    repo.put_prices(
                        self.db,
                        [(s.symbol, s.last_date, s.last_close) for s in secs if s.symbol in held and s.last_date and s.last_close is not None],
                    )
                except ProviderError as e:
                    log.warning("%s", e)
                    errors.append(str(e))
            if us:
                for sym in sorted(s for s in held if (sec := known.get(s)) is not None and not sec.is_tw):
                    try:
                        h = yahoo.chart(self.client, sym)
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


def _optional_date(v: object, label: str) -> str | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return Date.fromisoformat(str(v).strip()).isoformat()
    except ValueError:
        raise EntryError(f"{label}要是 YYYY-MM-DD 格式") from None
