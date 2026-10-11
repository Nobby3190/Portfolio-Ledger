from datetime import date
from decimal import Decimal as D

import httpx
import pytest

from portfolio_ledger import repo
from portfolio_ledger.db import Db
from portfolio_ledger.services import finance
from portfolio_ledger.services.ledger import EntryError, Ledger

TODAY = date(2026, 10, 11)


def no_http(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404, json={"chart": {"result": None, "error": {"description": "offline"}}})


@pytest.fixture
def lg():
    lg = Ledger(Db(":memory:"), httpx.Client(transport=httpx.MockTransport(no_http)), today=lambda: TODAY)
    lg.save_account({"name": "台新", "type": "bank"})
    lg.save_account({"name": "永豐", "type": "broker_tw"})
    lg.save_account({"name": "美元", "type": "bank", "currency": "USD"})
    lg.save_account({"name": "一年定存", "type": "deposit", "rate": "1.7", "start_date": "2026-04-11",
                     "maturity_date": "2026-11-01"})
    repo.put_fx(lg.db, [("USD", "2026-10-01", D(30)), ("USD", "2026-10-10", D(32))])
    return lg


def test_expense_goes_to_bank_and_creates_category(lg):
    p = lg.preview("支出 120 拉麵")
    assert p["status"] == "ready" and p["title"] == "支出 拉麵" and "新分類" in p["parts"]
    assert lg.preview("支出 80 餐")["title"] == "支出 餐飲"  # partial match
    lg.commit("支出 120 拉麵")
    t = repo.list_txs(lg.db)[-1]
    assert t.account_id == 1 and t.amount == D(-120)
    assert repo.get_category(lg.db, t.category_id).name == "拉麵"
    assert lg.tx_line(t.id) == "支出 120 拉麵 2026-10-11 @台新"


def test_transfer_two_legs_and_cross_currency(lg):
    lg.commit("收入 100000 薪資")
    tx_id = lg.commit("轉 32000 @台新 @美元 10/10")
    legs = [t for t in repo.list_txs(lg.db) if t.kind == "transfer"]
    assert [t.amount for t in legs] == [D(-32000), D(1000)]
    assert legs[1].fx_rate == D(32)
    line = lg.tx_line(tx_id)
    assert line == "轉 32000 2026-10-10 @台新 @美元 匯 32"
    lg.commit(line.replace("32000", "16000"), edit_id=legs[1].id)  # editing via either leg
    legs = [t for t in repo.list_txs(lg.db) if t.kind == "transfer"]
    assert [t.amount for t in legs] == [D(-16000), D(500)]
    s = lg.state()
    rows = [r for r in s["transactions"] if r["kind"] == "transfer"]
    assert len(rows) == 1 and rows[0]["to_account"] == "美元" and rows[0]["received"] == "500.00 USD"
    lg.delete(legs[0].id)
    assert not [t for t in repo.list_txs(lg.db) if t.kind == "transfer"]


def test_transfer_errors(lg):
    assert "兩個帳戶" in lg.preview("轉 5 @台新")["message"]
    assert "同一個" in lg.preview("轉 5 @台新 @台新")["message"]


def test_fx_position_average_cost(lg):
    lg.commit("收入 100000 薪資")
    lg.commit("轉 30000 @台新 @美元 匯 30 10/01")  # 1000 USD at 30
    lg.commit("轉 32000 @台新 @美元 10/10")  # 1000 USD at 32
    lg.commit("支出 500 旅行 @美元")  # spend a quarter at average cost 31
    fx = lg.state()["fx_positions"][0]
    assert fx["balance"] == "1,500.00" and fx["avg_rate"] == "31" and fx["rate"] == "32"
    assert fx["gain"] == "+1,500"  # 1500 × (32 − 31)


def test_deposit_accrual(lg):
    lg.commit("收入 300000 薪資")
    lg.commit("轉 100000 @台新 @一年定存 2026-04-11")
    d = lg.state()["deposits"][0]
    assert d["principal"] == "100,000" and d["days_left"] == 21 and d["soon"]
    assert d["accrued"] == "852"  # 100000 × 1.7% × 183/365 = 852.3
    alloc = {a["label"] for a in lg.state()["allocation"]}
    assert "定存" in alloc


def test_month_report_and_budgets(lg):
    lg.commit("收入 60000 薪資 10/05")
    lg.commit("支出 2000 餐飲 10/06")
    lg.commit("支出 1000 交通 09/20")
    lg.commit("支出 800 交通 10/07")
    food = next(c for c in repo.list_categories(lg.db, "expense") if c.name == "餐飲")
    finance.set_budget(lg, food.id, "5000")
    m = finance.month_report(lg, "2026-10")
    assert (m["income"], m["expense"], m["net"], m["savings_rate"]) == ("60,000", "2,800", "+57,200", "+95.33%")
    assert m["budget"] == "5,000" and m["budget_left"] == "2,200" and m["days_left"] == 21
    rows = {r["name"]: r for r in m["categories"]}
    assert rows["餐飲"]["budget_ratio"] == pytest.approx(0.4)
    assert rows["交通"]["last"] == "1,000" and rows["交通"]["delta"] == "−200"
    assert m["trend"][-1]["expense"] == 2800 and m["next"] == "2026-11"
    finance.set_total_budget(lg, "3000")
    assert finance.month_report(lg, "2026-10")["budget"] == "3,000"


def test_plan_goals_rebalance_fire(lg):
    lg.commit("收入 600000 薪資 2026-09-01")
    lg.commit("支出 30000 居住 2026-09-02")
    lg.commit("轉 200000 @台新 @一年定存 2026-09-03")
    finance.save_goal(lg, {"name": "緊急預備金", "target": "300000", "deadline": "2027-10-11", "account_ids": [1]})
    p = finance.plan(lg)
    g = p["goals"][0]
    assert g["current"] == "370,000" and g["done"]
    cash = next(r for r in p["rebalance"] if r["label"] == "現金")
    assert cash["current"] == pytest.approx(1.0) and cash["trade_sign"] == -1
    f = p["fire"]
    assert f["ready"] and f["auto"]["spend"] == "360000"  # one month of data, annualised
    finance.save_plan(lg, {"spend": "600000", "return": "5"})
    assert finance.plan(lg)["fire"]["target"] == "15,000,000"
    with pytest.raises(finance.FinanceError):
        finance.save_targets(lg, {"股票": "-1"})


def test_deposit_account_validation(lg):
    with pytest.raises(EntryError, match="到期日"):
        lg.save_account({"name": "x", "type": "deposit", "start_date": "2026-05-01", "maturity_date": "2026-04-01"})


def test_tx_fields_and_category_order(lg):
    lg.commit("收入 50000 薪資")
    lg.commit("支出 80 交通")
    tx_id = lg.commit("支出 120 餐飲 10/09 # 午餐")
    lg.commit("支出 90 餐飲")
    f = lg.tx_fields(tx_id)
    assert (f["kind"], f["amount"], f["category"], f["account"], f["date"], f["note"]) == (
        "expense", "120", "餐飲", "台新", "2026-10-09", "午餐")
    t = lg.tx_fields(lg.commit("轉 100 @台新 @一年定存"))
    assert (t["kind"], t["account"], t["to_account"]) == ("transfer", "台新", "一年定存")
    d = lg.tx_fields(lg.commit("存 5 @永豐"))
    assert (d["kind"], d["more"]) == ("more", "deposit")
    names = [c["name"] for c in lg.state()["categories"] if c["kind"] == "expense"]
    assert names[:2] == ["餐飲", "交通"]


def test_multi_currency_account(lg):
    lg.save_group({"name": "國泰外幣", "currencies": ["usd", "JPY"]})
    names = {a.name: a for a in repo.list_accounts(lg.db) if a.group_name == "國泰外幣"}
    assert set(names) == {"國泰外幣-USD", "國泰外幣-JPY"}
    repo.put_fx(lg.db, [("JPY", "2026-10-10", D("0.2"))])
    lg.commit("收入 200000 薪資")
    lg.commit("轉 20000 @台新 @國泰外幣-JPY 匯 0.2")
    assert "多種幣別" in lg.preview("支出 10 @國泰外幣")["message"]
    lg.commit("支出 1000 旅行 @國泰外幣-JPY")
    # 支出/收入 default stays on a TWD account
    assert lg.preview("支出 10")["parts"][0] == "台新"
    # rename and drop a currency: the used one is kept, the unused one is removed
    lg.save_group({"name": "外幣存款", "old_name": "國泰外幣", "currencies": ["USD"]})
    parts = {a.name: a.archived for a in repo.list_accounts(lg.db, True) if a.group_name == "外幣存款"}
    assert parts == {"外幣存款-USD": False, "外幣存款-JPY": True}
    with pytest.raises(EntryError, match="已經有"):
        lg.save_group({"name": "台新", "currencies": ["USD"]})
    with pytest.raises(EntryError, match="還有交易"):
        lg.delete_group("外幣存款")
    rows = [a for a in lg.state()["accounts"] if a["group_name"] == "外幣存款"]
    assert {r["currency"] for r in rows} == {"USD", "JPY"}
    assert next(r for r in rows if r["currency"] == "JPY")["value_twd"] == "19,800"


def test_group_part_picked_by_security_currency(lg):
    lg.save_group({"name": "複委託帳戶", "currencies": ["USD", "HKD"]})
    from portfolio_ledger.models import Security

    repo.upsert_securities(lg.db, [Security("VOO", "Vanguard S&P 500 ETF", "US", "USD", "etf", D(700), D(690), "2026-10-09")])
    p = lg.preview("買 VOO 1 700 @複委託帳戶")
    assert p["status"] == "ready" and "複委託帳戶-USD" in p["parts"]


def test_cathay_board_valuation_matches_bank_app():
    """The user's real case on 2026-10-11: 國泰 app showed 24,073; market mid-rates gave 24,138."""
    from pathlib import Path

    board = (Path(__file__).parent / "fixtures" / "cathay_board.html").read_text()

    def http(request: httpx.Request) -> httpx.Response:
        if "cathaybk" in str(request.url):
            return httpx.Response(200, text=board)
        return httpx.Response(404, json={"chart": {"result": None, "error": {"description": "offline"}}})

    lg = Ledger(Db(":memory:"), httpx.Client(transport=httpx.MockTransport(http)), today=lambda: TODAY)
    lg.save_account({"name": "國泰銀行/證券", "type": "broker_tw"})
    lg.save_group({"name": "外幣存款", "currencies": ["CNY", "JPY", "USD"]})
    repo.put_fx(lg.db, [("CNY", "2026-10-10", D("4.776")), ("JPY", "2026-10-09", D("0.1991")), ("USD", "2026-10-10", D("31.916"))])
    lg.commit("存 16393 @國泰銀行/證券")
    lg.commit("存 1195.07 @外幣存款-CNY")
    lg.commit("存 9980 @外幣存款-JPY")
    lg.commit("存 1.59 @外幣存款-USD")
    assert lg.state()["total"] == "24,138"  # market mid-rates

    lg.save_settings({"fx_source": "cathay"})
    lg.refresh(tw=False, us=False)
    assert lg.state()["total"] == "24,073"  # 國泰 即期買進, same as the bank app
    assert not [e for e in lg.status["errors"] if "國泰" in e]

    # Buying foreign currency without a rate uses the bank's selling rate (USD 32.0).
    p = lg.preview("轉 3200 @國泰銀行/證券 @外幣存款-USD")
    assert "轉入 100.00 USD" in p["parts"]

    lg.save_settings({"fx_source": "market"})
    assert lg.state()["total"] == "24,138"


def test_allocation_groups_and_credit_debt(lg):
    lg.save_account({"name": "玉山信用卡", "type": "credit"})
    lg.commit("收入 100000 薪資")
    lg.commit("轉 30000 @台新 @一年定存")
    lg.commit("支出 3250 購物 @玉山信用卡")
    g = lg.state()["allocation_groups"]
    cash = next(x for x in g["groups"] if x["key"] == "cash")
    assert [(i["label"], i["value"]) for i in cash["items"]] == [("台幣現金", "70,000"), ("定存", "30,000")]
    assert cash["ratio"] == pytest.approx(1.0)
    assert g["debts"] == [{"label": "信用卡欠款", "value": "−3,250"}]
    assert lg.state()["total"] == "96,750"  # debt still reduces the total


def test_life_plan_rows_and_projection(lg):
    lg.commit("收入 100000 薪資 2026-09-01")
    lg.commit("支出 40000 居住 2026-09-02")
    with pytest.raises(finance.FinanceError):
        finance.save_life_plan(lg, {"kind": "house", "name": "", "price": "100"})
    with pytest.raises(finance.FinanceError):
        finance.save_life_plan(lg, {"kind": "house", "name": "家", "price": "1", "loan_years": "3", "grace_years": "3"})
    # Only the price: paid in full, no month, no loan, not in the projection.
    finance.save_life_plan(lg, {"kind": "car", "name": "車", "price": "900000"})
    p = finance.plan(lg)
    car = p["life_plans"][0]
    assert car["need"] == "900,000" and car["loan"] is None and car["per_month"] is None
    assert p["fire"]["with_plans"] is None
    # A house with a month and a loan.
    pid = finance.save_life_plan(lg, {
        "kind": "house", "name": "兩房", "price": "12000000", "target_month": "2029-10", "down_ratio": "20",
        "one_off": "300000", "loan_rate": "2.2", "loan_years": "30", "monthly_cost": "3000", "account_ids": [1],
    })
    p = finance.plan(lg)
    house = next(x for x in p["life_plans"] if x["id"] == pid)
    assert house["need"] == "2,700,000" and house["saved"] == "60,000" and house["months_left"] == 35
    assert house["loan"]["principal"] == "9,600,000" and house["loan"]["payment"] == "36,451"
    assert house["burden"] == pytest.approx(0.3645, abs=1e-3) and house["burden_level"] == "note"  # 30–40%
    assert house["input"]["down_ratio"] == "20"
    f = p["fire"]["with_plans"]
    assert f["names"] == ["兩房"] and f["marks"][0]["year"] == 3
    finance.save_life_plan(lg, {**house["input"], "active": False})
    assert finance.plan(lg)["fire"]["with_plans"] is None
    finance.delete_life_plan(lg, pid)
    assert len(finance.plan(lg)["life_plans"]) == 1


def test_advice_from_ledger(lg):
    assert finance.advice(lg)["items"] == []  # nothing recorded yet
    lg.commit("收入 100000 薪資 2026-09-01")
    lg.commit("支出 40000 居住 2026-09-02")
    a = finance.advice(lg)
    got = {x["key"]: x["level"] for x in a["items"]}
    assert got["fund"] == "warn"  # 60,000 cash vs 40,000 a month
    assert got["savings"] == "ok" and "deposit" not in got  # the deposit account is empty
    finance.save_life_plan(lg, {"kind": "car", "name": "車", "price": "500000", "target_month": "2027-06"})
    assert {x["key"]: x["level"] for x in finance.advice(lg)["items"]}["near"] == "warn"
    finance.save_advice_thresholds(lg, {"fund_min_months": "1"})
    assert {x["key"]: x["level"] for x in finance.advice(lg)["items"]}["fund"] == "ok"
    assert finance.advice(lg)["thresholds"]["fund_min_months"] == "1"


def test_plans_without_accounts_share_net_worth(lg):
    lg.commit("收入 100000 薪資 2026-09-01")  # net worth 100,000
    finance.save_life_plan(lg, {"kind": "other", "name": "結婚", "price": "800000"})  # no month: last
    finance.save_life_plan(lg, {"kind": "car", "name": "車", "price": "70000", "target_month": "2027-06"})
    rows = {p["name"]: p for p in finance.plan(lg)["life_plans"]}
    assert rows["車"]["saved"] == "70,000" and rows["車"]["left"] is None
    assert rows["結婚"]["saved"] == "30,000" and rows["結婚"]["left"] == "770,000"


def test_claimed_accounts_leave_the_shared_pool(lg):
    lg.commit("收入 100000 薪資 2026-09-01")  # all in 台新 (id 1)
    finance.save_life_plan(lg, {"kind": "car", "name": "車", "price": "500000", "account_ids": [1]})
    finance.save_life_plan(lg, {"kind": "other", "name": "旅行", "price": "50000"})
    rows = {p["name"]: p for p in finance.plan(lg)["life_plans"]}
    assert rows["車"]["saved"] == "100,000" and rows["旅行"]["saved"] == "0"


def test_future_months_until_december(lg):
    finance.set_total_budget(lg, "30000")
    now = finance.month_report(lg)
    assert now["next"] == "2026-11" and [t["month"] for t in now["tabs"]][-3:] == ["2026-10", "2026-11", "2026-12"]
    assert now["tabs"][-1]["future"] and len(now["trend"]) == 6 and now["trend"][-1]["month"] == "2026-10"
    nov = finance.month_report(lg, "2026-11")
    assert nov["is_future"] and nov["budget_left"] == "30,000" and nov["days_left"] is None
    assert nov["trend"][-1]["month"] == "2026-10"  # the chart stops at this month
    assert finance.month_report(lg, "2026-12")["next"] is None
    with pytest.raises(finance.FinanceError):
        finance.month_report(lg, "2027-01")
    past = finance.month_report(lg, "2026-08")
    assert past["tabs"] == past["trend"] and not past["is_future"]
