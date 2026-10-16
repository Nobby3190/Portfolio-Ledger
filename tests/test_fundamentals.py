import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest

from portfolio_ledger import repo
from portfolio_ledger.db import Db
from portfolio_ledger.providers.finmind import parse_annual, parse_dividends
from portfolio_ledger.providers.twse import parse_valuations
from portfolio_ledger.providers.yahoo import parse_fundamentals
from portfolio_ledger.services import fundamentals, tracking
from portfolio_ledger.services.ledger import Ledger
from test_dividends import fake_http as base_http

F = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 11)


def load(name):
    return json.loads((F / name).read_text())


def finmind_fixture() -> dict:
    return {ds: load(f"finmind_{ds}.json")["data"] for ds in
            ("TaiwanStockFinancialStatements", "TaiwanStockBalanceSheet", "TaiwanStockCashFlowsStatement")}  # fmt: skip


def test_finmind_years_sum_quarters_and_take_year_end():
    a = parse_annual(finmind_fixture())
    assert sorted(a) == ["2023", "2024", "2025"]
    y = a["2024"]
    assert y["revenue"] == D("592644201000") + D("673510177000") + D("759692143000") + D("868461178000")
    assert y["ocf"] == D("1826177068000")  # cash flow is year to date: the 12-31 row
    assert y["capex"] == D("956006536000")  # stored positive
    assert y["shares"] == D("25932733200")  # 普通股股本 ÷ 10
    assert y["eps"] == D("45.26")


def test_finmind_drops_incomplete_years():
    data = finmind_fixture()
    data["TaiwanStockFinancialStatements"] = [r for r in data["TaiwanStockFinancialStatements"] if r["date"] != "2025-12-31"]
    assert "2025" not in parse_annual(data)


def test_finmind_dividends():
    rows = [{"CashExDividendTradingDate": "2026-06-12", "CashEarningsDistribution": 4.5, "CashStatutorySurplus": 0.5,
             "CashDividendPaymentDate": "2026-07-10"}, {"CashExDividendTradingDate": "", "CashEarningsDistribution": 0}]  # fmt: skip
    assert parse_dividends(rows) == [("2026-06-12", D("5.0"), "2026-07-10")]


def test_yahoo_fundamentals():
    a, cur = parse_fundamentals(load("yahoo_fund_aapl.json"))
    assert cur == "USD" and sorted(a)[-1] == "2025"
    y = a["2025"]
    assert y["capex"] > 0 and y["revenue"] == D("416161000000")
    assert "interest" not in y  # Apple stopped reporting it


def test_valuations():
    rows = {s: (pe, pb, y) for s, pe, pb, y in parse_valuations(load("bwibbu.json"))}
    assert rows["2330"] == (D("28.86"), D("10.04"), D("0.88"))
    assert rows["1101"][0] is None  # a loss: no 本益比


def test_checks_tsmc_pass():
    res = {c["key"]: c for c in fundamentals.checks(parse_annual(finmind_fixture()))}
    assert all(c["status"] == "pass" for c in res.values()), res
    assert res["roe"]["label"] == "平均 ROE（近 3 年）"


def test_checks_fail_and_missing():
    weak = {
        "2023": {"revenue": D(100), "gross_profit": D(10), "net_income": D(2), "equity": D(100), "ocf": D(1), "capex": D(5),
                 "ebit": D(3), "interest": D(2), "shares": D(100)},
        "2024": {"revenue": D(100), "gross_profit": D(12), "net_income": D(3), "equity": D(100), "ocf": D(1), "capex": D(5),
                 "ebit": D(3), "interest": D(2), "shares": D(130)},
    }  # fmt: skip
    res = {c["key"]: c["status"] for c in fundamentals.checks(weak)}
    assert res == {k: "fail" for k in ("roe", "fcf", "coverage", "gross_margin", "ocf_ni", "net_margin", "shares")}
    bank = {"2024": {"revenue": D(100), "net_income": D(30)}}
    res = {c["key"]: c["status"] for c in fundamentals.checks(bank)}
    assert set(res.values()) == {"na"}  # one year and no gross profit: never a fail by guess


def test_table_units():
    t = fundamentals.table(parse_annual(finmind_fixture()), D(100_000_000))
    assert t["years"] == ["2023", "2024", "2025"]
    rev = next(r for r in t["rows"] if r["key"] == "revenue")
    assert rev["values"][1] == "28,943"  # 億


def fund_http(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "finmindtrade" in url:
        ds = request.url.params["dataset"]
        if ds == "TaiwanStockDividend":
            return httpx.Response(200, json={"msg": "success", "status": 200, "data": []})
        return httpx.Response(200, json=load(f"finmind_{ds}.json"))
    if "fundamentals-timeseries" in url:
        return httpx.Response(200, json=load("yahoo_fund_aapl.json"))
    if "BWIBBU" in url:
        return httpx.Response(200, json=load("bwibbu.json"))
    return base_http(request)


@pytest.fixture
def lg():
    calls = []

    def http(request):
        calls.append(str(request.url))
        return fund_http(request)

    lg = Ledger(Db(":memory:"), httpx.Client(transport=httpx.MockTransport(http)), today=lambda: TODAY)
    lg.save_account({"name": "永豐", "type": "broker_tw"})
    lg.refresh()
    lg.calls = calls
    return lg


def test_report_caches_for_a_week(lg):
    r = tracking.fundamentals_report(lg, "2330")
    assert r["available"] and r["source"] == "FinMind" and r["unit"] == "台幣億"
    assert r["valuation"] == {"pe": "28.86", "pb": "10.04", "dividend_yield": "0.88%"}
    assert r["commands"][0]["text"] == "/earnings-review 台積電 最新"
    n = sum("finmindtrade" in u for u in lg.calls)
    tracking.fundamentals_report(lg, "2330")
    assert sum("finmindtrade" in u for u in lg.calls) == n  # cached
    tracking.fundamentals_report(lg, "2330", force=True)
    assert sum("finmindtrade" in u for u in lg.calls) > n


def test_report_etf_and_failure(lg):
    assert tracking.fundamentals_report(lg, "0050")["available"] is False
    repo.upsert_securities(lg.db, [repo.get_security(lg.db, "2330")])  # unchanged; then make FinMind fail
    lg.client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    r = tracking.fundamentals_report(lg, "2330")
    assert r["table"] is None and "FinMind" in r["error"]


def test_holdings_line(lg):
    lg.commit("存 2000000 @永豐")
    lg.commit("買 2330 1000 1050")
    line = tracking.holdings_line(lg)
    assert line.startswith("/portfolio-review 台積電 1000股 @1051.5元, 現金 ")
    assert "| 2330 | 台積電 |" in tracking.holdings_markdown(lg)


def test_fcf_check_uses_the_table_unit():
    fcf = next(c for c in fundamentals.checks(parse_annual(finmind_fixture()), D(100_000_000), "台幣億") if c["key"] == "fcf")
    assert fcf["value"].endswith(" 台幣億") and len(fcf["value"]) < 16
