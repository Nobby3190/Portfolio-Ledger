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


def parse_monthly(data: dict[str, Any], symbol: str) -> list[tuple[str, Decimal]]:
    """Monthly bars as (first day of the month, adjusted close): dividends reinvested."""
    chart = data.get("chart") or {}
    results = chart.get("result") or []
    if not results:
        err = (chart.get("error") or {}).get("description") or "沒有資料"
        raise ProviderError(f"找不到 {symbol}：{err}")
    r = results[0]
    offset = timedelta(seconds=int((r.get("meta") or {}).get("gmtoffset") or 0))
    ind = r.get("indicators") or {}
    adj = ((ind.get("adjclose") or [{}])[0].get("adjclose")) or ((ind.get("quote") or [{}])[0].get("close")) or []
    out: dict[str, Decimal] = {}
    for ts, c in zip(r.get("timestamp") or [], adj):
        price = dec(c)
        if price is None:
            continue
        month = (datetime.fromtimestamp(ts, UTC) + offset).date().replace(day=1).isoformat()
        out.setdefault(month, _round(price))  # the first bar of a month wins (Yahoo can add a partial one)
    return sorted(out.items())


def monthly(client: httpx.Client, symbol: str, start: datetime) -> list[tuple[str, Decimal]]:
    params = {"interval": "1mo", "period1": int(start.timestamp()), "period2": int(datetime.now(UTC).timestamp())}
    try:
        resp = client.get(CHART_URL.format(symbol=symbol), params=params)
        if resp.status_code != 404:
            resp.raise_for_status()
        return parse_monthly(resp.json(), symbol)
    except (httpx.HTTPError, ValueError) as e:
        raise ProviderError(f"Yahoo 下載 {symbol} 失敗：{e}") from e


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
