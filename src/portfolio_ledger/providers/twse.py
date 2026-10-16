"""Taiwan listed (TWSE) and OTC (TPEx) daily closes. Both OpenAPIs return the whole
market for the latest trading day only, so one call refreshes every name and price."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import httpx

from ..models import Security
from ..services.fees import tw_kind
from .base import ProviderError, dec, roc_date

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

# Stocks are 4 digits; ETFs start with 00 (0050, 00679B, 00400A). Drops warrants and the like.
_LISTED = re.compile(r"^(\d{4}|00\d{2,4}[A-Z]?)$")


def parse_twse(rows: list[dict[str, Any]]) -> list[Security]:
    return _parse(rows, "TWSE", code="Code", name="Name", close="ClosingPrice", change="Change")


def parse_tpex(rows: list[dict[str, Any]]) -> list[Security]:
    return _parse(rows, "TPEX", code="SecuritiesCompanyCode", name="CompanyName", close="Close", change="Change")


def _parse(rows: list[dict[str, Any]], market: str, *, code: str, name: str, close: str, change: str) -> list[Security]:
    out = []
    for r in rows:
        sym = str(r.get(code, "")).strip()
        if not _LISTED.match(sym):
            continue
        last = dec(r.get(close))
        chg = dec(r.get(change))
        out.append(
            Security(
                symbol=sym,
                name=str(r.get(name, "")).strip(),
                market=market,
                currency="TWD",
                kind=tw_kind(sym),
                last_close=last,
                prev_close=last - chg if last is not None and chg is not None else None,
                last_date=roc_date(str(r.get("Date", ""))) if last is not None else None,
            )
        )
    return out


EX_DIVIDEND_URL = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"


def parse_ex_dividends(rows: list[dict[str, Any]]) -> list[tuple[str, str, Decimal | None]]:
    """(symbol, ex date, cash per share or None if not announced) for upcoming 除息 (listed only).
    Rows that are 除權 only (stock dividends, rights) are skipped."""
    out = []
    for r in rows:
        sym = str(r.get("Code", "")).strip()
        day = roc_date(str(r.get("Date", "")))
        if not _LISTED.match(sym) or day is None or "息" not in str(r.get("Exdividend", "")):
            continue
        cash = dec(r.get("CashDividend"))
        out.append((sym, day, cash if cash else None))
    return out


def fetch_ex_dividends(client: httpx.Client) -> list[tuple[str, str, Decimal | None]]:
    try:
        resp = client.get(EX_DIVIDEND_URL)
        resp.raise_for_status()
        return parse_ex_dividends(resp.json())
    except (httpx.HTTPError, ValueError) as e:
        raise ProviderError(f"除權息預告下載失敗：{e}") from e


VALUATION_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"


def parse_valuations(rows: list[dict[str, Any]]) -> list[tuple[str, Decimal | None, Decimal | None, Decimal | None]]:
    """(symbol, 本益比, 股價淨值比, 殖利率 %) for listed stocks; 本益比 is empty for a loss."""
    out = []
    for r in rows:
        sym = str(r.get("Code", "")).strip()
        if _LISTED.match(sym):
            out.append((sym, dec(r.get("PEratio")), dec(r.get("PBratio")), dec(r.get("DividendYield"))))
    return out


def fetch_valuations(client: httpx.Client) -> list[tuple[str, Decimal | None, Decimal | None, Decimal | None]]:
    try:
        resp = client.get(VALUATION_URL)
        resp.raise_for_status()
        return parse_valuations(resp.json())
    except (httpx.HTTPError, ValueError) as e:
        raise ProviderError(f"本益比下載失敗：{e}") from e


def fetch_all(client: httpx.Client) -> list[Security]:
    out = []
    for url, parse in ((TWSE_URL, parse_twse), (TPEX_URL, parse_tpex)):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            out += parse(resp.json())
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(f"台股報價下載失敗：{e}") from e
    return out
