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
    "loan": "貸款",
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
    "repay": "還款",  # display only: stored as two transfer legs plus an interest expense
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
    principal: Decimal | None = None  # loans: amount borrowed, term and grace period (rate/start_date shared)
    term_years: Decimal | None = None
    grace_years: Decimal | None = None
    color: str | None = None  # '#rrggbb' picked by hand; None = from the bank/broker in the name
    statement_day: int | None = None  # credit cards: 結帳日 and 扣款日, day of month
    pay_day: int | None = None


@dataclass
class Category:
    id: int | None
    name: str
    kind: str  # income / expense
    budget: Decimal | None = None
    sort: int = 0
    archived: bool = False
    parent_id: int | None = None  # 子類別: the category it rolls up into (one level only)
    color: str | None = None  # a tone name (sky, plum…); None = from the name


# What a goal or plan counts as saved so far (DESIGN.md 規劃視圖「追蹤範圍」).
PLAN_SCOPES = {"cash": "現金與活存", "cash_deposit": "現金＋定存", "total": "總資產", "accounts": "自訂帳戶"}


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
    account_ids: list[int] | None = None  # used when scope is "accounts"
    active: bool = True  # included in the projection and health check
    sort: int = 0
    scope: str = "total"  # a key of PLAN_SCOPES; "total" shares the net worth with the other plans


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
    pe: Decimal | None = None  # 台股上市: 本益比, 股價淨值比, 殖利率 % (TWSE BWIBBU)
    pb: Decimal | None = None
    dividend_yield: Decimal | None = None

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
    recurring_id: int | None = None  # posted by a recurring rule
    balance: Decimal | None = None  # 期初餘額: the account's balance on this date; amount is derived from it


@dataclass
class Note:
    """投資筆記: why the user bought (or wants to buy), what would make them rethink, and a fair price band.
    One per symbol, shared by the holding and the watchlist."""

    symbol: str
    thesis: str = ""
    red_lines: str = ""  # one per line
    band_low: Decimal | None = None  # the security's currency
    band_high: Decimal | None = None
    review_months: int | None = None  # None = no review reminder
    last_review: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @property
    def red_line_list(self) -> list[str]:
        return [x.strip() for x in self.red_lines.splitlines() if x.strip()]


RECURRING_FREQS = {"monthly": "每月", "weekly": "每週", "yearly": "每年"}


@dataclass
class Recurring:
    id: int | None
    line: str  # a command line without a date
    freq: str  # monthly / weekly / yearly
    start_date: str  # anchors the day of month / weekday / month-day
    end_date: str | None = None
    last_date: str | None = None  # last date posted
    active: bool = True
    error: str | None = None
    sort: int = 0
