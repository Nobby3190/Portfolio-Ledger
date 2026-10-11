"""Plain records shared by repo, services and api. Money is always Decimal."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

ACCOUNT_TYPES = {
    "broker_tw": "台股券商",
    "broker_us": "複委託",
    "bank": "銀行",
    "cash": "現金",
    "credit": "信用卡",
    "deposit": "定存",
}
# Where income and expenses go when the line names no account.
SPENDING_TYPES = ("bank", "cash", "credit")
TX_KINDS = {
    "buy": "買進",
    "holding_in": "補登持股",
    "sell": "賣出",
    "cash_dividend": "現金股利",
    "stock_dividend": "股票股利",
    "split": "分割",
    "deposit": "存入",
    "withdraw": "提出",
    "income": "收入",
    "expense": "支出",
    "transfer": "轉帳",
}
INVESTMENT_KINDS = ("buy", "holding_in", "sell", "cash_dividend", "stock_dividend", "split")
TW_MARKETS = ("TWSE", "TPEX")


@dataclass
class Account:
    id: int | None
    name: str
    type: str
    currency: str
    fee_discount: Decimal | None = None
    fee_min: Decimal | None = None
    archived: bool = False
    sort: int = 0
    rate: Decimal | None = None  # time deposits: annual %, start and maturity dates
    start_date: str | None = None
    maturity_date: str | None = None
    group_name: str | None = None  # set on the per-currency parts of a multi-currency account


@dataclass
class Category:
    id: int | None
    name: str
    kind: str  # income / expense
    budget: Decimal | None = None
    sort: int = 0
    archived: bool = False


@dataclass
class Goal:
    id: int | None
    name: str
    target: Decimal
    deadline: str | None = None
    account_ids: list[int] | None = None  # None/empty: the whole net worth
    sort: int = 0


LIFE_PLAN_KINDS = {"house": "買房", "car": "買車", "other": "其他大筆支出"}


@dataclass
class LifePlan:
    id: int | None
    kind: str  # house / car / other
    name: str
    price: Decimal  # TWD, today's money
    target_month: str | None = None  # YYYY-MM
    down_ratio: Decimal | None = None  # %; None = paid in full
    one_off: Decimal | None = None
    loan_rate: Decimal | None = None  # annual %
    loan_years: Decimal | None = None
    grace_years: Decimal | None = None
    monthly_cost: Decimal | None = None
    rent_saved: Decimal | None = None
    account_ids: list[int] | None = None  # None/empty: the whole net worth
    active: bool = True
    sort: int = 0


@dataclass
class Security:
    symbol: str
    name: str
    market: str
    currency: str
    kind: str
    last_close: Decimal | None = None
    prev_close: Decimal | None = None
    last_date: str | None = None

    @property
    def is_tw(self) -> bool:
        return self.market in TW_MARKETS


@dataclass
class Tx:
    id: int | None
    account_id: int
    date: str
    kind: str
    symbol: str | None = None
    qty: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal = Decimal(0)
    fee: Decimal = Decimal(0)
    tax: Decimal = Decimal(0)
    fx_rate: Decimal | None = None
    category_id: int | None = None
    transfer_group: str | None = None
    note: str = ""
