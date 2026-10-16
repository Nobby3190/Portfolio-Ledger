import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest

from portfolio_ledger import repo
from portfolio_ledger.db import Db
from portfolio_ledger.providers.twse import parse_ex_dividends
from portfolio_ledger.services import dividends, finance
from portfolio_ledger.services.dividends import Paid
from portfolio_ledger.services.ledger import Ledger

F = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 11)


def fake_http(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "TWT48U" in url:
        return httpx.Response(200, json=json.loads((F / "twt48u.json").read_text()))
    if "twse" in url:
        return httpx.Response(200, json=json.loads((F / "twse.json").read_text()))
    if "tpex" in url:
        return httpx.Response(200, json=json.loads((F / "tpex.json").read_text()))
    if "USDTWD" in url:
        return httpx.Response(200, json={"chart": {"result": [{"meta": {"currency": "TWD", "gmtoffset": 3600},
            "timestamp": [1791480600, 1791567000], "indicators": {"quote": [{"close": [31.5, 31.916]}]}}]}})
    if "/VOO" in url:
        return httpx.Response(200, json=json.loads((F / "yahoo_voo.json").read_text()))
    return httpx.Response(404, json=json.loads((F / "yahoo_404.json").read_text()))


@pytest.fixture
def ledger():
    lg = Ledger(Db(":memory:"), httpx.Client(transport=httpx.MockTransport(fake_http)), today=lambda: TODAY)
    lg.save_account({"name": "永豐", "type": "broker_tw"})
    lg.save_account({"name": "複委託", "type": "broker_us"})
    lg.refresh()
    return lg


def test_parse_ex_dividends_keeps_cash_dividends_only():
    rows = parse_ex_dividends(json.loads((F / "twt48u.json").read_text()))
    assert rows == [
        ("00401A", "2026-10-15", D("0.131000")),
        ("0056", "2026-10-22", None),  # not announced yet
        ("2330", "2026-10-20", D("5.000000")),  # 權息 includes cash
    ]  # 1234 is 除權 only; 2317 has no date


def test_dividend_tax():
    assert dividends.dividend_tax(D(20000), "TWSE", "TWD") == (D(422), "二代健保")
    assert dividends.dividend_tax(D(19999), "TPEX", "TWD") == (D(0), None)
    assert dividends.dividend_tax(D(30000), "TWSE", "TWD")[0] == D(633)  # 633.0 truncated
    assert dividends.dividend_tax(D("100"), "US", "USD") == (D("30.00"), "預扣稅")
    assert dividends.dividend_tax(D("100"), "HK", "HKD") == (D(0), None)


def test_summarize_window_yield_and_cover():
    paid = [
        Paid("2025-10-01", "2330", D(1000)),  # older than 365 days: only in nothing
        Paid("2026-01-15", "2330", D(3000)),
        Paid("2025-12-20", "0056", D(2000)),  # sold out since
        Paid("2026-07-15", "2330", D(3000)),
    ]
    s = dividends.summarize(paid, {"2330": D(100_000)}, D(80_000), TODAY)
    assert s.ttm == D(8000) and s.ytd == D(6000)
    assert s.by_symbol == [("2330", D(6000)), ("0056", D(2000))]
    assert s.yield_on_cost == D("0.06")  # only symbols still held
    assert s.cover == D("0.1")
    assert dividends.summarize([], {}, None, TODAY).cover is None


def test_gross_dividend_takes_health_insurance_and_round_trips(ledger):
    ledger.commit("存 2000000 @永豐")
    ledger.commit("買 2330 1000 1050 2025-01-02")
    p = ledger.preview("息 2330 30000 稅前")
    assert "稅前 30,000 − 二代健保 633" in p["parts"] and p["total"] == "+29,367"
    ledger.commit("息 2330 30000 稅前 10/01")
    t = next(t for t in repo.list_txs(ledger.db) if t.kind == "cash_dividend")
    assert (t.amount, t.tax) == (D(29367), D(633))
    assert ledger.tx_line(t.id) == "息 2330 30000 稅前 2026-10-01 @永豐"
    assert ledger.tx_fields(t.id)["gross"] is True
    # an explicit 稅 wins and is kept on edit
    ledger.commit("息 2330 30000 稅前 稅 600 10/01", t.id)
    assert ledger.tx_line(t.id) == "息 2330 30000 稅前 2026-10-01 @永豐 稅 600"


def test_net_dividend_unchanged(ledger):
    ledger.commit("存 2000000 @永豐")
    ledger.commit("買 2330 1000 1050 2025-01-02")
    ledger.commit("息 2330 5000 10/01")
    t = next(t for t in repo.list_txs(ledger.db) if t.kind == "cash_dividend")
    assert (t.amount, t.tax) == (D(5000), D(0))
    assert ledger.tx_line(t.id) == "息 2330 5000 2026-10-01 @永豐"


def test_dividend_report_and_holding_fields(ledger):
    ledger.commit("存 2000000 @永豐")
    ledger.commit("買 2330 1000 1050 2025-01-02")
    ledger.commit("息 2330 5000 2026-04-10")
    ledger.save_account({"name": "台新", "type": "bank"})
    ledger.commit("支出 40000 餐飲 2026-09-10 @台新")
    r = finance.dividend_report(ledger)
    assert r["has"] and r["ttm"] == "5,000" and r["ytd"] == "5,000"
    assert r["by_symbol"][0]["symbol"] == "2330" and r["by_symbol"][0]["ratio"] == 1.0
    assert r["cover"] == "+1.04%"  # 5,000 ÷ (40,000 × 12)
    # 2330 除息 on 10/20 at 5.0 a share, from the TWT48U fixture
    up = r["upcoming"]
    assert [(u["symbol"], u["ex_date"], u["estimate"]) for u in up] == [("2330", "2026-10-20", "5,000")]
    h = ledger.state()["holdings"][0]
    assert h["dividends_ttm"] == "5,000" and h["yield_on_cost"].endswith("%")


def test_upcoming_without_amount(ledger):
    ledger.commit("存 2000000 @永豐")
    ledger.commit("買 0050 1000 180")
    repo.put_dividend_events(ledger.db, [("0050", "2026-11-01", None, None)])
    up = finance.dividend_report(ledger)["upcoming"]
    assert up[0]["symbol"] == "0050" and up[0]["cash"] is None and up[0]["estimate"] is None
    # a later feed with the amount fills it in; one without never erases it
    repo.put_dividend_events(ledger.db, [("0050", "2026-11-01", D("1.5"), None)])
    repo.put_dividend_events(ledger.db, [("0050", "2026-11-01", None, None)])
    assert finance.dividend_report(ledger)["upcoming"][0]["estimate"] == "1,500"


def test_xirr_needs_a_year(ledger):
    ledger.commit("存 2000000 @永豐")
    ledger.commit("買 2330 1000 1050 2026-01-02")
    s = ledger.state()
    assert s["xirr"] is None and s["holdings"][0]["xirr"] is None
    ledger.commit("買 2330 100 1000 2025-01-02")
    s = ledger.state()
    assert s["xirr"] is not None and s["xirr"].startswith("+")  # 1,050 → 2,550
    assert s["holdings"][0]["xirr"] == s["xirr"]
