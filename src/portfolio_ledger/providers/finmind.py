"""FinMind open data (api.finmindtrade.com): Taiwan financial statements and dividends.

Works without a key (hourly quota); FINMIND_TOKEN raises it. Tested 2026-10-15:
- TaiwanStockFinancialStatements: per quarter, so a year is the sum of four
- TaiwanStockCashFlowsStatement: year to date, so a year is the 12-31 row
- TaiwanStockBalanceSheet: at the date, so a year is the 12-31 row
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

import httpx

from .base import ProviderError, dec

URL = "https://api.finmindtrade.com/api/v4/data"

# Our field -> (dataset, FinMind type, how a year is built)
FIELDS: dict[str, tuple[str, str, str]] = {
    "revenue": ("TaiwanStockFinancialStatements", "Revenue", "sum"),
    "gross_profit": ("TaiwanStockFinancialStatements", "GrossProfit", "sum"),
    "ebit": ("TaiwanStockFinancialStatements", "OperatingIncome", "sum"),
    "net_income": ("TaiwanStockFinancialStatements", "EquityAttributableToOwnersOfParent", "sum"),  # 歸屬母公司
    "eps": ("TaiwanStockFinancialStatements", "EPS", "sum"),
    "equity": ("TaiwanStockBalanceSheet", "EquityAttributableToOwnersOfParent", "year_end"),
    "share_capital": ("TaiwanStockBalanceSheet", "OrdinaryShare", "year_end"),
    "ocf": ("TaiwanStockCashFlowsStatement", "CashFlowsFromOperatingActivities", "year_end"),
    "capex": ("TaiwanStockCashFlowsStatement", "PropertyAndPlantAndEquipment", "year_end"),  # negative: cash paid
    "interest": ("TaiwanStockCashFlowsStatement", "InterestExpense", "year_end"),
}
DATASETS = sorted({ds for ds, _, _ in FIELDS.values()})
PAR_VALUE = Decimal(10)  # 普通股股本 ÷ NT$10 = shares, true for nearly every listed company


def _get(client: httpx.Client, dataset: str, symbol: str, start: str) -> list[dict[str, Any]]:
    params = {"dataset": dataset, "data_id": symbol, "start_date": start}
    token = os.environ.get("FINMIND_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else None
    try:
        resp = client.get(URL, params=params, headers=headers)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise ProviderError(f"FinMind 下載失敗：{e}") from e
    if body.get("status") != 200:
        raise ProviderError(f"FinMind：{body.get('msg') or '沒有資料'}")
    return body.get("data") or []


def parse_annual(by_dataset: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Decimal]]:
    """{year: {field: value}} for complete years only (all four quarters of the income statement)."""
    raw: dict[tuple[str, str], dict[str, Decimal]] = {}  # (dataset, type) -> {date: value}
    for ds, rows in by_dataset.items():
        for r in rows:
            v = dec(r.get("value"))
            if v is not None and r.get("date"):
                raw.setdefault((ds, str(r.get("type"))), {})[str(r["date"])] = v
    years = sorted({d[:4] for series in raw.values() for d in series})
    out: dict[str, dict[str, Decimal]] = {}
    for y in years:
        row: dict[str, Decimal] = {}
        for field, (ds, typ, how) in FIELDS.items():
            series = raw.get((ds, typ), {})
            if how == "sum":
                qs = [series.get(f"{y}-{md}") for md in ("03-31", "06-30", "09-30", "12-31")]
                if all(q is not None for q in qs):
                    row[field] = sum(qs, Decimal(0))  # type: ignore[arg-type]
            elif (v := series.get(f"{y}-12-31")) is not None:
                row[field] = v
        if "capex" in row:
            row["capex"] = -row["capex"]  # store what was spent, positive
        if "share_capital" in row:
            row["shares"] = row.pop("share_capital") / PAR_VALUE
        if "revenue" in row:  # the year is complete
            out[y] = row
    return out


def annual(client: httpx.Client, symbol: str, start: str) -> dict[str, dict[str, Decimal]]:
    return parse_annual({ds: _get(client, ds, symbol, start) for ds in DATASETS})


def parse_dividends(rows: list[dict[str, Any]]) -> list[tuple[str, Decimal | None, str | None]]:
    """(ex date, cash per share, pay date) from TaiwanStockDividend; rows without a cash ex date skipped."""
    out = []
    for r in rows:
        ex = str(r.get("CashExDividendTradingDate") or "").strip()
        if not ex:
            continue
        cash = dec(r.get("CashEarningsDistribution")) or Decimal(0)
        cash += dec(r.get("CashStatutorySurplus")) or Decimal(0)
        pay = str(r.get("CashDividendPaymentDate") or "").strip() or None
        out.append((ex, cash or None, pay))
    return out


def dividends(client: httpx.Client, symbol: str, start: str) -> list[tuple[str, Decimal | None, str | None]]:
    return parse_dividends(_get(client, "TaiwanStockDividend", symbol, start))
