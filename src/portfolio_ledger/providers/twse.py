"""Taiwan listed (TWSE) and OTC (TPEx) daily closes. Both OpenAPIs return the whole
market for the latest trading day only, so one call refreshes every name and price."""

from __future__ import annotations

import re
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
