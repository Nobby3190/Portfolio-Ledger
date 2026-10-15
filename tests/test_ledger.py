import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest

from portfolio_ledger import repo
from portfolio_ledger.db import Db
from portfolio_ledger.services.ledger import EntryError, Ledger

F = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 11)


def fake_http(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
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


def test_refresh_loads_tw_list_and_fx(ledger):
    assert repo.count_tw_securities(ledger.db) == 5
    assert repo.fx_on(ledger.db, "USD")[0] == D("31.916")
    assert ledger.status["errors"] == []


def test_preview_buy_computes_fee(ledger):
    p = ledger.preview("買 2330 1000 1050")
    assert p["status"] == "ready"
    assert p["title"] == "買進 台積電 2330"
    assert "手續費 1,496" in p["parts"]
    assert p["total"] == "−1,051,496"


def test_preview_states(ledger):
    assert ledger.preview("")["status"] == "empty"
    assert ledger.preview("買 2330")["message"] == "還缺：股數、價格"
    assert ledger.preview("買 2330")["title"] == "台積電 2330"
    assert "找不到台股代號" in ledger.preview("買 1234 1 1")["message"]
    assert ledger.preview("台積")["results"][0]["symbol"] == "2330"
    assert "找不到代號 ZZZZ" in ledger.preview("買 ZZZZ 1 1")["message"]


def test_commit_value_and_sell_tax(ledger):
    ledger.commit("存 2000000 @永豐")
    ledger.commit("買 2330 1000 1050 10/01")
    ledger.commit("賣 2330 400 2550 10/08")
    s = ledger.state()
    h = s["holdings"][0]
    assert h["qty"] == "600" and h["close"] == "2,550.00"
    by_kind = {t.kind: t for t in repo.list_txs(ledger.db)}
    sell = by_kind["sell"]
    assert sell.tax == D(3060) and sell.fee == D(1453)
    with pytest.raises(EntryError, match="只持有 600 股"):
        ledger.commit("賣 2330 601 2550")
    # deleting the buy would make the sell impossible
    with pytest.raises(EntryError):
        ledger.delete(by_kind["buy"].id)


def test_usd_trade_uses_fx_and_right_account(ledger):
    ledger.commit("存 10000 @複委託")
    ledger.commit("買 VOO 10 700 費 3")
    t = repo.list_txs(ledger.db)[-1]
    assert t.account_id == 2 and t.amount == D(-7003) and t.fx_rate == D("31.916")
    # A TWD brokerage account can buy it too (台幣交割): converted at that day's rate.
    p = ledger.preview("買 VOO 1 700 @永豐")
    assert p["status"] == "ready" and p["total"] == "−22,341"  # 700 × 31.916
    s = ledger.state()
    assert s["allocation"][0]["label"] == "美股"
    # 10 * 715.59 * 31.916 + 2997 * 31.916
    assert s["total"] == "324,040"


def test_edit_roundtrip(ledger):
    ledger.commit("存 2000000 @永豐")
    tx_id = ledger.commit("買 2330 1000 1050 10/01 # 第一筆")
    line = ledger.tx_line(tx_id)
    assert line == "買 2330 1000 1050 2026-10-01 @永豐 # 第一筆"
    ledger.commit(line.replace("1000", "2000"), edit_id=tx_id)
    assert repo.get_tx(ledger.db, tx_id).qty == D(2000)
    assert len(repo.list_txs(ledger.db)) == 2


def test_fee_override_survives_edit(ledger):
    ledger.commit("存 100000 @永豐")
    tx_id = ledger.commit("買 0050 100 114.95 費 1")
    assert "費 1" in ledger.tx_line(tx_id)


def test_snapshot_written(ledger):
    ledger.commit("存 5000 @永豐")
    assert repo.list_snapshots(ledger.db) == [("2026-10-11", D(5000))]


def test_account_rules(ledger):
    with pytest.raises(EntryError, match="空白"):
        ledger.save_account({"name": "我的 帳戶", "type": "bank"})
    with pytest.raises(EntryError, match="已經有"):
        ledger.save_account({"name": "永豐", "type": "bank"})
    ledger.commit("存 1 @永豐")
    with pytest.raises(EntryError, match="不能刪除"):
        ledger.delete_account(1)


def test_account_color(ledger):
    acc_id = ledger.save_account({"name": "玉山", "type": "credit", "color": "#00857C"})
    ledger.save_group({"name": "外幣", "type": "bank", "currencies": ["USD", "JPY"], "color": "#4a6178"})
    s = ledger.state()
    assert next(a for a in s["accounts"] if a["id"] == acc_id)["color"] == "#00857c"
    assert {a["color"] for a in s["accounts"] if a["group_name"] == "外幣"} == {"#4a6178"}
    assert next(g for g in s["account_groups"] if g["name"] == "外幣")["color"] == "#4a6178"
    ledger.save_account({"id": acc_id, "name": "玉山", "type": "credit", "color": ""})  # back to automatic
    assert next(a for a in ledger.state()["accounts"] if a["id"] == acc_id)["color"] is None
    with pytest.raises(EntryError, match="顏色"):
        ledger.save_account({"name": "台新", "type": "bank", "color": "red"})


def test_future_date_rejected(ledger):
    assert "未來" in ledger.preview("存 5 2026-12-01 @永豐")["message"]


def test_backfill_past_purchase_leaves_cash_alone(ledger):
    ledger.save_settings({"fee_discount": "0.28", "fee_min": "1"})
    ledger.commit("存 16393 @永豐")  # today's real balance already reflects old purchases
    p = ledger.preview("補 2330 100 580 2023-05-02")
    assert p["status"] == "ready" and "不從現金扣款" in p["parts"] and p["total"] is None
    tx_id = ledger.commit("補 2330 100 580 2023-05-02")
    s = ledger.state()
    acct = next(a for a in s["accounts"] if a["name"] == "永豐")
    assert acct["cash"] == "16,393"
    h = s["holdings"][0]
    # cost = 58,000 + fee floor(58000 × 0.1425% × 0.28) = 23
    assert h["avg_cost"] == "580.23"
    assert ledger.tx_line(tx_id) == "補 2330 100 580 2023-05-02 @永豐"
    f = ledger.tx_fields(tx_id)
    assert (f["kind"], f["backfill"], f["qty"], f["price"]) == ("buy", True, "100", "580", )
    # selling later adds cash and books profit against the backfilled cost
    ledger.commit("賣 2330 100 2550")
    sell = repo.list_txs(ledger.db)[-1]
    assert sell.amount == D(255000) - sell.fee - sell.tax
    assert ledger.state()["closed"][0]["realized"].startswith("+")


@pytest.fixture
def hk_ledger():
    def http(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/0700.HK" in url or "/2800.HK" in url:  # (2800 reuses the 0700 fixture)
            return httpx.Response(200, json=json.loads((F / "yahoo_0700.json").read_text()))
        if "twse" in url:
            return httpx.Response(200, json=json.loads((F / "twse.json").read_text()))
        if "tpex" in url:
            return httpx.Response(200, json=json.loads((F / "tpex.json").read_text()))
        if "HKDTWD" in url:
            return httpx.Response(200, json={"chart": {"result": [{"meta": {"currency": "TWD", "gmtoffset": 28800},
                "timestamp": [1791567000], "indicators": {"quote": [{"close": [4.07]}]}}]}})
        return httpx.Response(404, json=json.loads((F / "yahoo_404.json").read_text()))

    lg = Ledger(Db(":memory:"), httpx.Client(transport=httpx.MockTransport(http)), today=lambda: TODAY)
    lg.save_account({"name": "國泰", "type": "broker_tw"})
    lg.refresh()
    return lg


def test_hong_kong_stock_settled_in_twd(hk_ledger):
    """國泰複委託 with 台幣交割: HKD-priced holding, TWD cash, valued at the current HKD rate."""
    lg = hk_ledger
    # a bare number: Taiwan miss, but the HK code is offered
    assert "港股請打 0700.HK" in lg.preview("買 0700 100 420")["message"]
    assert [r["symbol"] for r in lg.preview("0700")["results"]] == ["0700.HK"]
    lg.commit("存 100000 @國泰")
    tx_id = lg.commit("買 700.HK 100 420 匯 4.1 費 50 稅 0")
    t = repo.get_tx(lg.db, tx_id)
    # 100 × 420 HKD × 4.1 = 172,200 TWD + 50 fee
    assert t.symbol == "0700.HK" and t.account_id == 1 and t.amount == D(-172250) and t.fx_rate == D("4.1")
    assert lg.tx_line(tx_id) == "買 0700.HK 100 420 2026-10-11 @國泰 費 50 稅 0 匯 4.1"
    s = lg.state()
    h = s["holdings"][0]
    assert h["currency"] == "HKD" and h["value"] == "42,480.00"  # 100 × 424.8 HKD
    assert h["value_twd"] == "172,894"  # × 4.07 today
    assert h["unrealized"] == "+644"  # 172,893.6 − 172,250
    assert next(a for a in s["accounts"] if a["name"] == "國泰")["cash"] == "−72,250"
    assert [a["label"] for a in s["allocation"] if a["label"] == "港股"] == ["港股"]
    # selling converts back; the default rate is that day's HKD rate when none is given
    lg.commit("賣 0700.HK 100 430 費 0 稅 0")
    sell = repo.list_txs(lg.db)[-1]
    assert sell.amount == D("175010") and sell.fx_rate == D("4.07")  # 43,000 × 4.07
    assert lg.state()["closed"][0]["realized"] == "+2,760"


def test_hong_kong_backfill_and_hkd_brokerage(hk_ledger):
    lg = hk_ledger
    lg.commit("補 0700.HK 100 300 2024-01-02 匯 4 費 40 稅 0")
    h = lg.state()["holdings"][0]
    assert h["avg_cost"] == "1,200.40" and h["cost_currency"] == "TWD"  # (30,000 HKD × 4 + 40) / 100
    # with an HKD brokerage account, it is preferred over 台幣交割
    lg.save_group({"name": "國泰複委託", "type": "broker_us", "currencies": ["USD", "HKD"]})
    p = lg.preview("買 0700.HK 10 420")
    assert "國泰複委託-HKD" in p["parts"]


def test_hong_kong_auto_fees_and_total_cost_backfill(hk_ledger):
    lg = hk_ledger
    lg.commit("存 200000 @國泰")
    # auto: 42,480 HKD → fee 111.59 + stamp 43 HKD, × 4.1 → 458 + 176 TWD
    tx_id = lg.commit("買 0700.HK 100 424.8 匯 4.1")
    t = repo.get_tx(lg.db, tx_id)
    assert (t.fee, t.tax, t.amount) == (D(458), D(176), D(-(174168 + 458 + 176)))
    assert lg.tx_line(tx_id) == "買 0700.HK 100 424.8 2026-10-11 @國泰 匯 4.1"  # auto fees not spelled out

    # backfill from the 國泰 app's 庫存: 總股數 15, 成交均價 1907.67, 總成本 28,640 (fees included)
    lg.commit("補 2330 15 1907.67 2025-06-02 總 28640")
    tw = next(h for h in lg.state()["holdings"] if h["symbol"] == "2330")
    assert tw["avg_cost"] == "1,909.3333"  # 28,640 / 15, exactly the app's cost
    # the same for a 台幣交割 HK holding: 總成本 in TWD becomes the cost, the rate absorbs the fees
    lg.commit("補 2800.HK 1000 20 2024-03-01 總 82000")
    book_cost = sum(p.cost for p in lg._replay(repo.list_txs(lg.db)).positions.values() if p.symbol == "2800.HK")
    assert book_cost == D(82000)
    with pytest.raises(EntryError, match="只用在補登"):
        lg.commit("買 2330 1 1000 總 1000")
