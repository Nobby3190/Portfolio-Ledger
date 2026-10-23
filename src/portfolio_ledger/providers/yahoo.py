"""Yahoo Finance chart API (unofficial): US quotes and history, and FX rates (USDTWD=X)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from .base import History, ProviderError, dec

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def parse_chart(data: dict[str, Any], symbol: str) -> History:
    chart = data.get("chart") or {}
    results = chart.get("result") or []
    if not results:
        err = (chart.get("error") or {}).get("description") or "沒有資料"
        raise ProviderError(f"找不到 {symbol}：{err}")
    r = results[0]
    meta = r.get("meta") or {}
    offset = timedelta(seconds=int(meta.get("gmtoffset") or 0))
    stamps = r.get("timestamp") or []
    quotes = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []

    by_day: dict[str, Decimal] = {}
    for ts, c in zip(stamps, quotes):
        close = dec(c)
        if close is None:
            continue
        day = (datetime.fromtimestamp(ts, UTC) + offset).date().isoformat()
        by_day[day] = _round(close)  # later bars of the same day (intraday) win
    if meta.get("regularMarketTime") and (price := dec(meta.get("regularMarketPrice"))) is not None:
        day = (datetime.fromtimestamp(int(meta["regularMarketTime"]), UTC) + offset).date().isoformat()
        by_day[day] = _round(price)

    kind = "etf" if meta.get("instrumentType") == "ETF" else "stock"
    return History(
        symbol=symbol,
        name=meta.get("longName") or meta.get("shortName") or symbol,
        currency=(meta.get("currency") or "USD").upper(),
        kind=kind,
        closes=sorted(by_day.items()),
    )


def _round(d: Decimal) -> Decimal:
    # Yahoo sends floats like 31.925399780273438; four places is plenty for prices and FX.
    return d.quantize(Decimal("0.0001")).normalize()


def chart(client: httpx.Client, symbol: str, range_: str = "5d") -> History:
    try:
        resp = client.get(CHART_URL.format(symbol=symbol), params={"range": range_, "interval": "1d"})
        if resp.status_code != 404:  # an unknown symbol is a 404 whose body says why
            resp.raise_for_status()
        return parse_chart(resp.json(), symbol)
    except (httpx.HTTPError, ValueError) as e:
        raise ProviderError(f"Yahoo 下載 {symbol} 失敗：{e}") from e


def fx_symbol(currency: str) -> str:
    return f"{currency}TWD=X"


SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"


def search(client: httpx.Client, q: str, limit: int = 6) -> list[tuple[str, str, str]]:
    """Name search for non-Taiwan listings: [(symbol, name, exchange)], stocks and ETFs only."""
    try:
        resp = client.get(SEARCH_URL, params={"q": q, "quotesCount": limit, "newsCount": 0})
        resp.raise_for_status()
        quotes = resp.json().get("quotes") or []
    except (httpx.HTTPError, ValueError) as e:
        raise ProviderError(f"Yahoo 搜尋失敗：{e}") from e
    out = []
    for item in quotes:
        if item.get("quoteType") in ("EQUITY", "ETF") and item.get("symbol"):
            sym = str(item["symbol"]).upper()
            if sym.endswith((".TW", ".TWO")):
                continue  # Taiwan listings come from the exchanges' own lists
            out.append((sym, item.get("longname") or item.get("shortname") or sym, item.get("exchange") or ""))
    return out


FUNDAMENTALS_URL = "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}"
# Yahoo annual series -> our field (DESIGN.md 5.4; tested 2026-10-15, no crumb needed)
FUNDAMENTAL_TYPES = {
    "annualTotalRevenue": "revenue",
    "annualGrossProfit": "gross_profit",
    "annualEBIT": "ebit",
    "annualNetIncomeCommonStockholders": "net_income",
    "annualDilutedEPS": "eps",
    "annualStockholdersEquity": "equity",
    "annualOrdinarySharesNumber": "shares",
    "annualOperatingCashFlow": "ocf",
    "annualCapitalExpenditure": "capex",  # negative: cash paid
    "annualInterestExpense": "interest",
}


def parse_fundamentals(data: dict[str, Any]) -> tuple[dict[str, dict[str, Decimal]], str | None]:
    """({fiscal year: {field: value}}, reporting currency). The year is the one the fiscal year ends in."""
    out: dict[str, dict[str, Decimal]] = {}
    currency = None
    for r in ((data.get("timeseries") or {}).get("result")) or []:
        typ = ((r.get("meta") or {}).get("type") or [None])[0]
        field = FUNDAMENTAL_TYPES.get(typ or "")
        if field is None:
            continue
        for item in r.get(typ) or []:
            if not item:
                continue
            v = dec((item.get("reportedValue") or {}).get("raw"))
            day = str(item.get("asOfDate") or "")
            if v is None or len(day) < 4:
                continue
            if field == "capex":
                v = -v  # what was spent, positive
            out.setdefault(day[:4], {})[field] = v
            if field == "revenue":
                currency = item.get("currencyCode") or currency
    return {y: row for y, row in out.items() if "revenue" in row}, currency


def fundamentals(client: httpx.Client, symbol: str) -> tuple[dict[str, dict[str, Decimal]], str | None]:
    now = int(datetime.now(UTC).timestamp())
    params = {"type": ",".join(FUNDAMENTAL_TYPES), "period1": now - 7 * 366 * 86400, "period2": now}
    try:
        resp = client.get(FUNDAMENTALS_URL.format(symbol=symbol), params=params)
        resp.raise_for_status()
        return parse_fundamentals(resp.json())
    except (httpx.HTTPError, ValueError) as e:
        raise ProviderError(f"Yahoo 財報下載 {symbol} 失敗：{e}") from e
