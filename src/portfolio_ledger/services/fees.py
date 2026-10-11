"""Taiwan brokerage fee and securities transaction tax. Brokers truncate both to whole dollars."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

FEE_RATE = Decimal("0.001425")
TAX_STOCK = Decimal("0.003")
TAX_ETF = Decimal("0.001")
TAX_DAYTRADE = Decimal("0.0015")
# Bond ETFs are exempt from the transaction tax through this date (inclusive).
BOND_ETF_EXEMPT_UNTIL = "2026-12-31"

DEFAULT_DISCOUNT = Decimal(1)
DEFAULT_MIN_FEE = Decimal(20)


def _floor(d: Decimal) -> Decimal:
    return d.to_integral_value(rounding=ROUND_FLOOR)


def tw_kind(code: str) -> str:
    """stock / etf / bond_etf, from the code alone: ETFs start with 00, bond ETFs end in B."""
    if code.startswith("00"):
        return "bond_etf" if code.endswith("B") else "etf"
    return "stock"


def tw_fee(gross: Decimal, discount: Decimal = DEFAULT_DISCOUNT, minimum: Decimal = DEFAULT_MIN_FEE) -> Decimal:
    if gross <= 0:
        return Decimal(0)
    return max(_floor(gross * FEE_RATE * discount), minimum)


def tw_tax(gross: Decimal, kind: str, date: str, daytrade: bool = False) -> Decimal:
    """Sell side only; callers don't call this for buys."""
    if kind == "bond_etf":
        rate = Decimal(0) if date <= BOND_ETF_EXEMPT_UNTIL else TAX_ETF
    elif kind == "etf":
        rate = TAX_ETF
    else:
        rate = TAX_DAYTRADE if daytrade else TAX_STOCK
    return _floor(gross * rate)


# Hong Kong, 國泰證券 複委託 online orders (cathaysec.com.tw 商品與費用 - 港股, checked 2026-10-11).
# All in HKD on the trade value; charged on both buys and sells.
HK_COMMISSION = Decimal("0.0025")
HK_MIN_COMMISSION = Decimal(40)
HK_STAMP_DUTY = Decimal("0.001")  # rounded up to a whole dollar; ETFs are exempt
HK_LEVIES = Decimal("0.000042") + Decimal("0.000027") + Decimal("0.0000565") + Decimal("0.0000015")
# 證交所費用 0.0042%, 證監會交易徵費 0.0027%, 交易費 0.00565%, 會財局徵費 0.00015%


def hk_fees(gross: Decimal, kind: str) -> tuple[Decimal, Decimal]:
    """(fee, tax) in HKD for a Hong Kong trade worth `gross` HKD: fee = commission + levies, tax = stamp duty."""
    if gross <= 0:
        return Decimal(0), Decimal(0)
    cents = Decimal("0.01")
    commission = max((gross * HK_COMMISSION).quantize(cents, rounding=ROUND_HALF_UP), HK_MIN_COMMISSION)
    levies = (gross * HK_LEVIES).quantize(cents, rounding=ROUND_HALF_UP)
    stamp = Decimal(0) if kind in ("etf", "bond_etf") else (gross * HK_STAMP_DUTY).to_integral_value(rounding=ROUND_CEILING)
    return commission + levies, stamp
