"""子類別: 購物 renamed 消費, with 數碼 and 運動 under it."""

from datetime import date

import httpx
import pytest

from portfolio_ledger import repo
from portfolio_ledger.db import Db
from portfolio_ledger.models import Recurring
from portfolio_ledger.services import finance
from portfolio_ledger.services.ledger import Ledger

TODAY = date(2026, 10, 11)


@pytest.fixture
def lg():
    lg = Ledger(Db(":memory:"), httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))), today=lambda: TODAY)
    lg.save_account({"name": "台新", "type": "bank"})
    return lg


def cat(lg, name):
    return next(c for c in repo.list_categories(lg.db) if c.name == name)


def group(lg):
    """購物 → 消費, with 數碼 and 運動 under it."""
    lg.commit("支出 500 數碼 10/01")
    lg.commit("支出 300 運動 10/02")
    lg.commit("支出 200 購物 10/03")
    lg.commit("支出 100 數碼 09/05")
    lg.commit("支出 1000 餐飲 10/04")
    finance.rename_category(lg, cat(lg, "購物").id, "消費")
    shop = cat(lg, "消費").id
    finance.set_category_parent(lg, cat(lg, "數碼").id, shop)
    finance.set_category_parent(lg, cat(lg, "運動").id, shop)
    return shop


def test_month_report_rolls_subcategories_up(lg):
    shop = group(lg)
    finance.set_budget(lg, shop, "2000")
    finance.set_budget(lg, cat(lg, "數碼").id, "400")
    finance.set_budget(lg, cat(lg, "餐飲").id, "3000")
    m = finance.month_report(lg, "2026-10")
    rows = {r["name"]: r for r in m["categories"]}
    assert set(rows) >= {"消費", "餐飲"} and "數碼" not in rows and "運動" not in rows
    c = rows["消費"]
    assert c["spent"] == "1,000" and c["budget_ratio"] == pytest.approx(0.5) and c["last"] == "100"
    assert c["share"] == pytest.approx(0.5)
    kids = {k["name"]: k for k in c["children"]}
    assert list(kids) == ["數碼", "運動", "消費（未細分）"]
    assert kids["數碼"]["spent"] == "500" and kids["數碼"]["budget_ratio"] == pytest.approx(1.25)
    assert kids["數碼"]["share"] == pytest.approx(0.5) and kids["消費（未細分）"]["own"]
    assert "children" not in rows["餐飲"]
    assert m["budget"] == "5,000"  # 消費 2000 + 餐飲 3000; 數碼's own 400 is inside 消費's


def test_year_report_rolls_subcategories_up(lg):
    group(lg)
    y = finance.year_report(lg, 2026)
    rows = {r["name"]: r for r in y["categories"]}
    assert rows["消費"]["amount"] == "1,100" and "數碼" not in rows
    assert [k["name"] for k in rows["消費"]["children"]] == ["數碼", "運動", "消費（未細分）"]


def test_subcategory_still_entered_by_its_own_name(lg):
    shop = group(lg)
    assert lg.preview("支出 50 數碼")["title"] == "支出 數碼"
    assert lg.preview("支出 50 消費")["title"] == "支出 消費"
    chips = {c["name"]: c for c in lg.state()["categories"]}
    assert chips["數碼"]["parent_id"] == shop and chips["數碼"]["count"] == 2


def test_rename_rewrites_recurring_rules(lg):
    for line in ("支出 99 購 @台新 # 雜貨", "支出 30 購物 # iCloud", "支出 10 餐飲", "收入 5 購物"):
        repo.save_recurring(lg.db, Recurring(None, line, "monthly", "2026-10-01"))
    finance.rename_category(lg, cat(lg, "購物").id, "消費")
    lines = [r.line for r in repo.list_recurring(lg.db)]
    assert lines == ["支出 99 消費 @台新 # 雜貨", "支出 30 消費 # iCloud", "支出 10 餐飲", "收入 5 購物"]


@pytest.mark.parametrize("name", ["", "有 空白", "123", "@消費", "10/01", "餐飲"])
def test_rename_rejects_bad_names(lg, name):
    with pytest.raises(finance.FinanceError):
        finance.rename_category(lg, cat(lg, "購物").id, name)


def test_only_one_level(lg):
    shop = group(lg)
    digital = cat(lg, "數碼").id
    with pytest.raises(finance.FinanceError, match="子類別底下不能再分"):
        finance.set_category_parent(lg, cat(lg, "餐飲").id, digital)
    with pytest.raises(finance.FinanceError, match="底下還有子類別"):
        finance.set_category_parent(lg, shop, cat(lg, "餐飲").id)
    with pytest.raises(finance.FinanceError, match="收入和支出"):
        finance.set_category_parent(lg, cat(lg, "薪資").id, shop)
    with pytest.raises(finance.FinanceError, match="自己"):
        finance.set_category_parent(lg, shop, shop)
    finance.set_category_parent(lg, digital, None)
    assert "數碼" in {r["name"] for r in finance.month_report(lg, "2026-10")["categories"]}
