from datetime import date
from decimal import Decimal as D

import pytest

from portfolio_ledger.services.quick import ParseError, format_command, parse

TODAY = date(2026, 10, 11)


def test_buy_basic():
    c = parse("買 2330 1000 1050", TODAY)
    assert (c.action, c.symbol, c.qty, c.price, c.date, c.missing) == ("buy", "2330", D(1000), D(1050), None, ())


def test_glued_action_lots_and_modifiers():
    c = parse("買2330 2張 1,050.5 10/08 @永豐 費 20 稅0 # 加碼", TODAY)
    assert c.qty == D(2000) and c.price == D("1050.5")
    assert c.date == "2026-10-08" and c.account == "永豐"
    assert c.fee == D(20) and c.tax == D(0) and c.note == "加碼"


def test_english_and_lowercase_symbol():
    c = parse("sell voo 2 700 fx 31.9", TODAY)
    assert (c.action, c.symbol, c.fx) == ("sell", "VOO", D("31.9"))


def test_month_day_in_future_means_last_year():
    assert parse("存 100 12/30", TODAY).date == "2025-12-30"
    assert parse("存 100 2026-01-02", TODAY).date == "2026-01-02"


def test_missing_fields_reported():
    assert parse("買 2330", TODAY).missing == ("qty", "price")
    assert parse("存", TODAY).missing == ("amount",)


def test_split_ratio_forms():
    assert parse("拆 NVDA 10", TODAY).qty == D(10)
    assert parse("拆 NVDA 1:4", TODAY).qty == D(4)


def test_lookup_when_no_action():
    c = parse("台積電", TODAY)
    assert c.action == "lookup" and c.symbol == "台積電"


@pytest.mark.parametrize(
    "line,msg",
    [
        ("吃 2330 1 1", "看不懂"),
        ("買 2330 abc 10", "不是數字"),
        ("買 2330 1 1 9", "多了"),
        ("存 -5", "大於 0"),
        ("存 5 13/45", "日期"),
        ("買 2330 0 10", "大於 0"),
    ],
)
def test_errors(line, msg):
    with pytest.raises(ParseError, match=msg):
        parse(line, TODAY)


def test_format_roundtrip():
    line = format_command("buy", symbol="2330", qty=D("1000"), price=D("1050.00"), date="2026-10-08",
                          account="永豐", fee=D(20), note="加碼")
    assert line == "買 2330 1000 1050 2026-10-08 @永豐 費 20 # 加碼"
    c = parse(line, TODAY)
    assert (c.symbol, c.qty, c.price, c.fee, c.note) == ("2330", D(1000), D(1050), D(20), "加碼")


def test_expense_amount_and_category_any_order():
    a = parse("支出 120 午餐", TODAY)
    b = parse("花 午餐 120 # 便當", TODAY)
    assert (a.action, a.amount, a.category) == ("expense", D(120), "午餐")
    assert (b.amount, b.category, b.note) == (D(120), "午餐", "便當")
    assert parse("花120", TODAY).category is None


def test_income_and_transfer():
    c = parse("收入 60000 薪資 @台新", TODAY)
    assert (c.action, c.category, c.account) == ("income", "薪資", "台新")
    t = parse("轉 10000 @台新 @永豐 匯 31.9", TODAY)
    assert (t.action, t.amount, t.account, t.to_account, t.fx) == ("transfer", D(10000), "台新", "永豐", D("31.9"))


@pytest.mark.parametrize(
    "line,msg",
    [("支出 午餐 晚餐 100", "分類只能一個詞"), ("支出 1 2", "多了"), ("存 5 @a @b", "只能指定一個帳戶"),
     ("轉 5 @a @b @c", "太多")],
)
def test_cash_flow_errors(line, msg):
    with pytest.raises(ParseError, match=msg):
        parse(line, TODAY)


def test_format_flow_and_transfer():
    assert format_command("expense", amount=D(120), category="午餐", account="台新") == "支出 120 午餐 @台新"
    assert format_command("transfer", amount=D(5), account="a", to_account="b") == "轉 5 @a @b"


def test_full_width_input_from_ime():
    c = parse("支出　１５０　午餐　＠台新　＃便當", TODAY)
    assert (c.amount, c.category, c.account, c.note) == (D(150), "午餐", "台新", "便當")
