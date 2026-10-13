"""Parse one line of the command bar, e.g. `買 2330 1張 1050 10/08 @永豐 費 20 # 加碼`.

Pure syntax only: symbols, accounts and fees are resolved later (services/entry.py).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date as Date
from decimal import Decimal, InvalidOperation

ACTIONS = {
    "買": "buy", "買進": "buy", "buy": "buy", "b": "buy",
    "賣": "sell", "賣出": "sell", "sell": "sell", "s": "sell",
    "補": "holding_in", "補登": "holding_in", "backfill": "holding_in",
    "息": "cash_dividend", "股利": "cash_dividend", "股息": "cash_dividend", "div": "cash_dividend",
    "配股": "stock_dividend", "sdiv": "stock_dividend",
    "拆": "split", "分割": "split", "split": "split",
    "存": "deposit", "存入": "deposit", "入": "deposit", "in": "deposit",
    "提": "withdraw", "提出": "withdraw", "出": "withdraw", "out": "withdraw",
    "支出": "expense", "花": "expense", "expense": "expense", "exp": "expense",
    "收入": "income", "income": "income",
    "轉": "transfer", "轉帳": "transfer", "transfer": "transfer", "tf": "transfer",
    "還": "repay", "還款": "repay", "repay": "repay",
    "定額": "dca", "定期定額": "dca", "dca": "dca",
}  # fmt: skip
# Chinese keywords may be glued to what follows ("買2330"); longest first so 買進 beats 買.
_GLUED = sorted((k for k in ACTIONS if not k.isascii()), key=len, reverse=True)
_OVERRIDES = {"費": "fee", "fee": "fee", "稅": "tax", "tax": "tax", "匯": "fx", "fx": "fx", "總": "total", "total": "total",
              "利": "interest", "interest": "interest"}  # fmt: skip

# Positional fields each action needs, in order.
FIELDS = {
    "buy": ("symbol", "qty", "price"),
    "sell": ("symbol", "qty", "price"),
    "holding_in": ("symbol", "qty", "price"),  # a past purchase whose cash already left the balance
    "cash_dividend": ("symbol", "amount"),
    "stock_dividend": ("symbol", "qty"),
    "split": ("symbol", "qty"),
    "deposit": ("amount",),
    "withdraw": ("amount",),
    "income": ("amount",),  # plus an optional category, in any order (see _cash_flow)
    "expense": ("amount",),
    "transfer": ("amount",),
    "repay": (),  # the amount is optional: the loan's scheduled payment (see _repay)
    "dca": ("symbol", "amount"),  # 定期定額: a fixed amount, bought at that day's close
}
FIELD_NAMES = {"symbol": "代號", "qty": "股數", "price": "價格", "amount": "金額"}
CATEGORY_KINDS = ("income", "expense")

_DATE_MD = re.compile(r"^(\d{1,2})/(\d{1,2})$")
_DATE_FULL = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$")
_SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,11}$")


class ParseError(ValueError):
    pass


@dataclass
class Command:
    action: str  # a key of FIELDS, or "lookup" when the line has no action word
    symbol: str | None = None
    qty: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None
    date: str | None = None
    account: str | None = None
    to_account: str | None = None  # transfer destination: the second @
    category: str | None = None
    fee: Decimal | None = None
    tax: Decimal | None = None
    fx: Decimal | None = None
    total: Decimal | None = None  # 補登: the broker app's total cost (account currency, fees included)
    interest: Decimal | None = None  # 還: the bank's interest when it differs from balance × rate ÷ 12
    opening: bool = False  # 存 … 期初: the amount is the account's balance on that date
    note: str = ""
    missing: tuple[str, ...] = ()  # positional fields not typed yet


def number(tok: str) -> Decimal:
    t = tok.replace(",", "").lstrip("$")
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise ParseError(f"「{tok}」不是數字") from None
    if not d.is_finite():
        raise ParseError(f"「{tok}」不是數字")
    return d


def quantity(tok: str) -> Decimal:
    """Shares; 張 means board lots of 1,000, 股 is just a unit."""
    if tok.endswith("張"):
        return number(tok[:-1]) * 1000
    return number(tok.removesuffix("股"))


def ratio(tok: str) -> Decimal:
    """Split ratio: `10`, `1:10` or `1拆10` all mean one share becomes ten."""
    for sep in (":", "拆", "比"):
        if sep in tok:
            a, b = tok.split(sep, 1)
            return number(b) / number(a)
    return number(tok)


def parse_date(tok: str, today: Date) -> str | None:
    if m := _DATE_FULL.match(tok):
        y, mo, d = map(int, m.groups())
    elif m := _DATE_MD.match(tok):
        mo, d = map(int, m.groups())
        y = today.year
        try:
            if Date(y, mo, d) > today:  # 12/30 typed in January means last year
                y -= 1
        except ValueError:
            pass
    else:
        return None
    try:
        return Date(y, mo, d).isoformat()
    except ValueError:
        raise ParseError(f"「{tok}」不是有效的日期") from None


def tokenize(text: str) -> tuple[list[str], str]:
    # NFKC folds full-width input from Chinese IMEs (１５０、＠台新、＃、ideographic space) to plain ASCII.
    body, _, note = unicodedata.normalize("NFKC", text).partition("#")
    toks = body.split()
    if toks and toks[0] not in ACTIONS:
        for k in _GLUED:
            if toks[0].startswith(k):
                toks[0:1] = [k, toks[0][len(k):]]
                break
    return toks, note.strip()


def parse(text: str, today: Date) -> Command:
    toks, note = tokenize(text)
    if not toks:
        raise ParseError("")
    action = ACTIONS.get(toks[0].lower())
    if action is None:
        if len(toks) == 1:
            return Command("lookup", symbol=toks[0])
        raise ParseError(f"看不懂「{toks[0]}」：開頭要是 買、賣、補、息、配股、拆、存、提、支出、收入、轉、還、定額")

    cmd = Command(action, note=note)
    positional: list[str] = []
    rest = toks[1:]
    i = 0
    while i < len(rest):
        tok = rest[i]
        low = tok.lower()
        if tok.startswith("@"):
            if len(tok) == 1:
                raise ParseError("@ 後面要接帳戶名稱")
            if cmd.account is None:
                cmd.account = tok[1:]
            elif action in ("transfer", "repay") and cmd.to_account is None:
                cmd.to_account = tok[1:]
            else:
                raise ParseError("帳戶寫太多個了" if action in ("transfer", "repay") else "只能指定一個帳戶")
        elif low in ("期初", "opening") and action == "deposit":
            cmd.opening = True
        elif (d := parse_date(tok, today)) is not None:
            cmd.date = d
        elif low in _OVERRIDES:
            if i + 1 >= len(rest):
                raise ParseError(f"「{tok}」後面要接數字")
            setattr(cmd, _OVERRIDES[low], number(rest[i + 1]))
            i += 1
        elif tok[0] in "費稅匯總利" and len(tok) > 1 and _is_number(tok[1:]):  # 費20; but 利息 is a category
            setattr(cmd, _OVERRIDES[tok[0]], number(tok[1:]))
        else:
            positional.append(tok)
        i += 1

    if action in CATEGORY_KINDS:
        return _cash_flow(cmd, positional)
    if action == "repay":
        return _repay(cmd, positional)
    fields = FIELDS[action]
    if len(positional) > len(fields):
        extra = " ".join(positional[len(fields) :])
        raise ParseError(f"多了「{extra}」")
    for name, tok in zip(fields, positional):
        if name == "symbol":
            if not _SYMBOL.match(tok):
                raise ParseError(f"「{tok}」不像股票代號")
            cmd.symbol = tok.upper()
        elif name == "qty":
            cmd.qty = ratio(tok) if action == "split" else quantity(tok)
            if cmd.qty <= 0:
                raise ParseError("股數要大於 0")
        elif name == "price":
            cmd.price = number(tok)
            if cmd.price <= 0:
                raise ParseError("價格要大於 0")
        elif name == "amount":
            cmd.amount = number(tok)
            if cmd.amount <= 0 and not cmd.opening:  # an opening balance may be a debt (credit card)
                raise ParseError("金額要大於 0")
    cmd.missing = fields[len(positional) :]
    return cmd


def _cash_flow(cmd: Command, positional: list[str]) -> Command:
    """Income/expense: one number (the amount) and at most one word (the category), either order."""
    words = []
    for tok in positional:
        try:
            amount = number(tok)
        except ParseError:
            words.append(tok)
            continue
        if cmd.amount is not None:
            raise ParseError(f"多了「{tok}」")
        if amount <= 0:
            raise ParseError("金額要大於 0")
        cmd.amount = amount
    if len(words) > 1:
        raise ParseError(f"分類只能一個詞，多了「{' '.join(words[1:])}」；說明請寫在 # 後面")
    cmd.category = words[0] if words else None
    cmd.missing = () if cmd.amount is not None else ("amount",)
    return cmd


def _is_number(tok: str) -> bool:
    try:
        number(tok)
    except ParseError:
        return False
    return True


def _repay(cmd: Command, positional: list[str]) -> Command:
    """還: an optional amount (default: the scheduled payment); the loan and the payer are the two @s."""
    if len(positional) > 1:
        raise ParseError(f"多了「{' '.join(positional[1:])}」；說明請寫在 # 後面")
    if positional:
        cmd.amount = number(positional[0])
        if cmd.amount <= 0:
            raise ParseError("金額要大於 0")
    if cmd.interest is not None and cmd.interest < 0:
        raise ParseError("利息不能是負數")
    return cmd


def format_command(
    action: str,
    *,
    symbol: str | None = None,
    qty: Decimal | None = None,
    price: Decimal | None = None,
    amount: Decimal | None = None,
    date: str | None = None,
    account: str | None = None,
    to_account: str | None = None,
    category: str | None = None,
    fee: Decimal | None = None,
    tax: Decimal | None = None,
    fx: Decimal | None = None,
    total: Decimal | None = None,
    interest: Decimal | None = None,
    opening: bool = False,
    note: str = "",
) -> str:
    """The inverse of parse(): the line a stored transaction is edited as."""
    word = {"buy": "買", "holding_in": "補", "sell": "賣", "cash_dividend": "息", "stock_dividend": "配股", "split": "拆",
            "deposit": "存", "withdraw": "提", "income": "收入", "expense": "支出", "transfer": "轉",
            "repay": "還", "dca": "定額"}[action]  # fmt: skip
    parts = [word]
    values = {"symbol": symbol, "qty": qty, "price": price, "amount": amount}
    for name in FIELDS[action]:
        v = values[name]
        parts.append(v if isinstance(v, str) else _plain(v))
    if action == "repay" and amount is not None:
        parts.append(_plain(amount))
    if opening:
        parts.append("期初")
    if category:
        parts.append(category)
    if date:
        parts.append(date)
    if account:
        parts.append(f"@{account}")
    if to_account:
        parts.append(f"@{to_account}")
    for word, v in (("費", fee), ("稅", tax), ("匯", fx), ("總", total), ("利", interest)):
        if v is not None:
            parts.append(f"{word} {_plain(v)}")
    line = " ".join(parts)
    return f"{line} # {note}" if note else line


def _plain(d: Decimal | None) -> str:
    return "" if d is None else format(d.normalize(), "f")
