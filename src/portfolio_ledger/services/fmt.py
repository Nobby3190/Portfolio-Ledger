"""Decimal -> display strings. The frontend formats nothing numeric itself."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CURRENCY_NAMES = {
    "TWD": "台幣", "USD": "美元", "JPY": "日圓", "EUR": "歐元", "CNY": "人民幣", "HKD": "港幣",
    "AUD": "澳幣", "GBP": "英鎊", "SGD": "新加坡幣", "CAD": "加幣", "CHF": "瑞士法郎",
    "NZD": "紐幣", "ZAR": "南非幣", "KRW": "韓元",
}  # fmt: skip
_PLACES = {"TWD": 0, "JPY": 0, "KRW": 0}


def places(currency: str) -> int:
    return _PLACES.get(currency, 2)


def round_money(d: Decimal, currency: str) -> Decimal:
    return d.quantize(Decimal(1).scaleb(-places(currency)), rounding=ROUND_HALF_UP)


def money(d: Decimal | None, currency: str = "TWD", signed: bool = False) -> str | None:
    """'1,051,496' / '−1,051,496' / '+38,201'; signed adds '+' to positives. Uses a real minus sign."""
    if d is None:
        return None
    r = round_money(d, currency)
    if r == 0:
        r = abs(r)  # no "-0"
    body = f"{abs(r):,.{places(currency)}f}"
    if r < 0:
        return f"−{body}"
    return f"+{body}" if signed and r > 0 else body


def pct(num: Decimal, den: Decimal) -> str | None:
    if den == 0:
        return None
    r = (num / den * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if r == 0:
        r = abs(r)
    return f"+{r}%" if r > 0 else f"−{abs(r)}%" if r < 0 else f"{r}%"


def price(d: Decimal | None) -> str | None:
    """Prices keep their own precision, at least two places: 2,550.00 / 11.13 / 715.59."""
    if d is None:
        return None
    d = d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)  # averages can repeat forever
    n = d.normalize()
    exp = n.as_tuple().exponent
    dp = max(2, -exp) if isinstance(exp, int) else 2
    return f"{d:,.{dp}f}"


def qty(d: Decimal | None) -> str | None:
    if d is None:
        return None
    n = d.normalize()
    exp = n.as_tuple().exponent
    dp = -exp if isinstance(exp, int) and exp < 0 else 0
    return f"{d:,.{dp}f}"


def sign(d: Decimal) -> int:
    return 1 if d > 0 else -1 if d < 0 else 0
