"""v1.3 記帳強化: auto-category, loans (還), recurring entries, year report."""

from datetime import date
from decimal import Decimal as D

import httpx
import pytest

from portfolio_ledger import repo
from portfolio_ledger.db import Db
from portfolio_ledger.models import Recurring
from portfolio_ledger.services import finance, planner, recurring
from portfolio_ledger.api import Api
from portfolio_ledger.services.ledger import DCA_CONFIRMED, EntryError, Ledger
from portfolio_ledger.services.quick import parse

TODAY = date(2026, 10, 11)


def no_http(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404, json={"chart": {"result": None, "error": {"description": "offline"}}})


class Clock:
    def __init__(self, d: date) -> None:
        self.d = d

    def __call__(self) -> date:
        return self.d


@pytest.fixture
def clock():
    return Clock(TODAY)


@pytest.fixture
def lg(clock):
    lg = Ledger(Db(":memory:"), httpx.Client(transport=httpx.MockTransport(no_http)), today=clock)
    lg.save_account({"name": "台新", "type": "bank"})
    lg.save_account({"name": "房貸", "type": "loan", "principal": "1200000", "rate": "2.4", "term_years": "20",
                     "start_date": "2026-01-10"})  # fmt: skip
    lg.commit("存 500000 @台新 2026-01-01")
    return lg


def cat_of(lg, tx_id):
    return repo.get_category(lg.db, repo.get_tx(lg.db, tx_id).category_id).name


# ── 自動分類 ──


def test_category_guessed_from_same_note(lg):
    lg.commit("支出 120 餐飲 10/01 # 全聯")
    p = lg.preview("支出 300 # 全聯")
    assert p["title"] == "支出 餐飲" and "依過去紀錄" in p["parts"] and p["guessed_category"] == "餐飲"
    assert cat_of(lg, lg.commit("支出 300 # 全聯")) == "餐飲"
    # An explicit category always wins.
    assert lg.preview("支出 300 購物 # 全聯")["guessed_category"] is None


def test_category_guess_by_containment_needs_one_answer(lg):
    lg.commit("支出 120 餐飲 10/01 # 全聯 晚餐")
    assert lg.preview("支出 50 # 全聯")["title"] == "支出 餐飲"
    lg.commit("支出 80 購物 10/02 # 全聯 衛生紙")
    assert lg.preview("支出 50 # 全聯")["title"] == "支出 其他"  # 餐飲 or 購物: no guess
    assert lg.preview("支出 50 # 全聯 晚餐")["title"] == "支出 餐飲"  # an exact note still decides


def test_category_guess_ignores_old_entries_and_other_kind(lg):
    lg.commit("支出 120 餐飲 2025-09-01 # 全聯")
    assert lg.preview("支出 50 # 全聯")["title"] == "支出 其他"
    lg.commit("收入 100 獎金 10/01 # 全聯")
    assert lg.preview("支出 50 # 全聯")["title"] == "支出 其他"


def test_glued_override_does_not_eat_a_category():
    assert parse("收入 6000 利息", TODAY).category == "利息"
    assert parse("還 30000 @房貸 利9800", TODAY).interest == D(9800)


# ── 貸款 ──


def test_repay_splits_principal_and_interest(lg):
    lg.commit("轉 1200000 @房貸 @台新 2026-01-10")
    p = lg.preview("還 @房貸 2026-02-10")
    pay = D(str(round(planner.amortize(1200000, 0.024, 20).payment)))
    assert p["status"] == "ready" and p["title"] == "還款 房貸"
    assert "利息 2,400" in p["parts"] and f"本金 {pay - 2400:,}" in p["parts"]
    tx_id = lg.commit("還 @房貸 2026-02-10")
    group = repo.txs_in_group(lg.db, repo.get_tx(lg.db, tx_id).transfer_group)
    assert sorted((t.kind, t.amount) for t in group) == sorted(
        [("transfer", -(pay - 2400)), ("transfer", pay - 2400), ("expense", D(-2400))]
    )
    assert cat_of(lg, next(t.id for t in group if t.kind == "expense")) == "貸款利息"
    # One row in the list, editable as one line.
    rows = [r for r in lg.state()["transactions"] if r["kind"] == "repay"]
    assert len(rows) == 1 and rows[0]["to_account"] == "房貸" and rows[0]["account"] == "台新"
    assert lg.tx_line(group[0].id) == f"還 {pay} 2026-02-10 @房貸 @台新"
    # Interest is only the expense: it counts in 收支, the principal does not.
    assert finance.month_report(lg, "2026-02")["expense"] == "2,400"


def test_repay_interest_follows_the_balance(lg):
    lg.commit("轉 1200000 @房貸 @台新 2026-01-10")
    lg.commit("轉 200000 @台新 @房貸 2026-01-20")  # prepaid principal
    assert "利息 2,000" in lg.preview("還 @房貸 2026-02-10")["parts"]
    p = lg.preview("還 20000 @房貸 @台新 利 1990 2026-02-10")
    assert "利息 1,990" in p["parts"] and "本金 18,010" in p["parts"]
    tx_id = lg.commit("還 20000 @房貸 @台新 利 1990 2026-02-10")
    assert lg.tx_line(tx_id) == "還 20000 2026-02-10 @房貸 @台新 利 1990"  # differs from computed → kept


def test_repay_errors_and_payoff(lg):
    with pytest.raises(EntryError, match="已經還清"):
        lg.commit("還 @房貸")
    lg.commit("轉 1000 @房貸 @台新 2026-01-10")
    with pytest.raises(EntryError, match="貸款帳戶"):
        lg.commit("還 100 @台新")
    with pytest.raises(EntryError, match="利息"):
        lg.commit("還 1 @房貸 利 5")
    lg.commit("還 5000 @房貸 2026-02-10")  # more than owed: principal stops at the balance
    assert repo.list_txs(lg.db)[-1].amount == D(-2)  # interest 1000 × 0.2% = 2
    assert lg.state()["loans"][0]["done"]


def test_repay_in_grace_period_is_interest_only(lg):
    lg.save_account({"id": 2, "name": "房貸", "type": "loan", "principal": "1200000", "rate": "2.4", "term_years": "20",
                     "grace_years": "2", "start_date": "2026-01-10"})  # fmt: skip
    lg.commit("轉 1200000 @房貸 @台新 2026-01-10")
    tx_id = lg.commit("還 @房貸 2026-02-10")
    group = repo.txs_in_group(lg.db, repo.get_tx(lg.db, tx_id).transfer_group)
    assert sorted((t.kind, t.amount) for t in group) == [("expense", D(-2400)), ("transfer", D(0))]
    assert lg.tx_line(tx_id) == "還 2400 2026-02-10 @房貸 @台新"


def test_loan_card_and_debts(lg):
    lg.commit("轉 1200000 @房貸 @台新 2026-01-10")
    lg.commit("轉 120000 @台新 @房貸 2026-03-01")
    s = lg.state()
    loan = s["loans"][0]
    assert loan["owed"] == "1,080,000" and loan["ratio"] == pytest.approx(0.1)
    assert loan["payment"] and loan["payoff"] < "2046-01" and loan["interest_left"]
    assert any(d["label"] == "房貸" for d in s["allocation_groups"]["debts"])
    lg.commit("收入 60000 薪資 10/05")
    burden = next(i for i in finance.advice(lg)["items"] if i["key"] == "loan")
    assert burden["level"] == "ok" and "房貸" in "".join(str(x) for x in burden["detail"])


# ── 週期性收支 ──


def test_due_dates_month_end_and_weekly():
    r = Recurring(None, "支出 1", "monthly", "2026-01-31")
    assert recurring.due_dates(r, date(2026, 4, 30)) == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]
    r.last_date = "2026-02-28"
    assert recurring.due_dates(r, date(2026, 4, 1)) == ["2026-03-31"]
    w = Recurring(None, "支出 1", "weekly", "2026-10-01", end_date="2026-10-20")
    assert recurring.due_dates(w, date(2026, 12, 1)) == ["2026-10-01", "2026-10-08", "2026-10-15"]
    y = Recurring(None, "支出 1", "yearly", "2024-02-29")
    assert recurring.due_dates(y, date(2026, 10, 1)) == ["2024-02-29", "2025-02-28", "2026-02-28"]
    assert recurring.dated("支出 1 # 房租 #2", "2026-01-01") == "支出 1 2026-01-01 # 房租 #2"


def test_recurring_backfills_then_posts_each_new_month(lg, clock):
    data = {"line": "支出 15000 居住 @台新 # 房租", "freq": "monthly", "start_date": "2026-08-05"}
    assert recurring.backfill_count(lg, data) == 3
    assert recurring.save(lg, data) == 3
    posted = [t for t in repo.list_txs(lg.db) if t.recurring_id]
    assert [t.date for t in posted] == ["2026-08-05", "2026-09-05", "2026-10-05"]
    assert recurring.run_due(lg) == 0  # nothing twice
    clock.d = date(2026, 11, 5)
    assert recurring.run_due(lg) == 1
    rows = lg.state()["transactions"]
    assert rows[0]["recurring"] and rows[0]["date"] == "2026-11-05"
    rule = recurring.rows(lg)[0]
    assert rule["next_date"] == "2026-12-05" and rule["title"] == "房租" and rule["amount"] == "−15,000"


def test_recurring_pause_resume_and_errors(lg, clock):
    recurring.save(lg, {"line": "收入 60000 薪資", "freq": "monthly", "start_date": "2026-10-01"})
    rule_id = recurring.rows(lg)[0]["id"]
    recurring.save(lg, {"id": rule_id, "line": "收入 60000 薪資", "start_date": "2026-10-01", "active": False})
    clock.d = date(2027, 1, 15)
    assert recurring.run_due(lg) == 0
    # Resuming skips what fell due while paused.
    assert recurring.save(lg, {"id": rule_id, "line": "收入 60000 薪資", "start_date": "2026-10-01"}) == 0
    clock.d = date(2027, 2, 1)
    assert recurring.run_due(lg) == 1
    with pytest.raises(EntryError, match="日期"):
        recurring.save(lg, {"line": "支出 100 10/01"})
    with pytest.raises(EntryError, match="週期性只能"):
        recurring.save(lg, {"line": "買 2330 1 1000"})
    # A posting that fails keeps the error and stops that rule there.
    lg.commit("轉 1000 @房貸 @台新 2027-01-10")
    assert recurring.save(lg, {"line": "還 @房貸", "start_date": "2027-02-01"}) == 1  # pays it off
    clock.d = date(2027, 3, 1)
    assert recurring.run_due(lg) == 1  # the salary; the loan rule fails
    rule = recurring.rows(lg)[-1]
    assert rule["error"] == "2027-03-01：「房貸」已經還清了" and rule["next_date"] == "2027-03-01"


def test_recurring_from_commit_and_repay_rule(lg, clock):
    lg.commit("轉 1200000 @房貸 @台新 2026-01-10")
    tx_id = lg.commit("還 @房貸 2026-10-10")
    recurring.from_commit(lg, "還 @房貸 2026-10-10", tx_id)
    assert all(t.recurring_id for t in repo.txs_in_group(lg.db, repo.get_tx(lg.db, tx_id).transfer_group))
    clock.d = date(2026, 11, 10)
    assert recurring.run_due(lg) == 1
    rows = [r for r in lg.state()["transactions"] if r["kind"] == "repay"]
    assert len(rows) == 2 and rows[0]["date"] == "2026-11-10" and rows[0]["recurring"]


def test_editing_a_posting_keeps_its_mark(lg):
    recurring.save(lg, {"line": "支出 100 # 停車", "start_date": "2026-10-01"})
    t = next(t for t in repo.list_txs(lg.db) if t.recurring_id)
    lg.commit("支出 130 2026-10-01 # 停車", edit_id=t.id)
    assert repo.get_tx(lg.db, t.id).recurring_id == t.recurring_id


# ── 年度報表 ──


def test_year_report(lg):
    lg.commit("收入 50000 薪資 2025-03-05")
    lg.commit("支出 20000 居住 2025-03-06")
    lg.commit("收入 60000 薪資 2026-03-05")
    lg.commit("支出 15000 居住 2026-03-06")
    lg.commit("支出 3000 餐飲 2026-09-06")
    y = finance.year_report(lg)
    assert (y["year"], y["income"], y["expense"], y["net"], y["savings_rate"]) == (2026, "60,000", "18,000", "+42,000", "+70.00%")
    assert y["per_month"] == "1,800" and y["elapsed"] == 10 and y["compare_label"] == "比 2025 年 1–10 月"
    lg.commit("支出 9000 居住 2025-11-06")  # after October: not part of the same-period comparison
    assert finance.year_report(lg)["vs_last"]["expense"]["delta"] == "−2,000"
    assert y["vs_last"]["expense"]["delta"] == "−2,000" and y["vs_last"]["savings_rate"] == "+60.00%"
    home = next(c for c in y["categories"] if c["name"] == "居住")
    assert home["amount"] == "15,000" and home["delta"] == "−5,000" and home["share"] == pytest.approx(15000 / 18000)
    assert [t["year"] for t in y["tabs"]] == [2025, 2026]
    assert len(y["trend"]) == 12 and y["trend"][2]["income"] == 60000 and y["trend"][11]["future"]
    last = finance.year_report(lg, 2025)
    assert last["expense"] == "29,000" and last["elapsed"] == 12 and last["vs_last"]["expense"] is None
    with pytest.raises(finance.FinanceError):
        finance.year_report(lg, 2027)


# ── 期初餘額 ──


def bal(lg, name):
    return next(a["cash"] for a in lg.state()["accounts"] if a["name"] == name)


def test_opening_balance_absorbs_backfilled_entries(clock):
    lg = Ledger(Db(":memory:"), httpx.Client(transport=httpx.MockTransport(no_http)), today=clock)
    lg.save_account({"name": "台新", "type": "bank"})
    p = lg.preview("存 169380 期初 @台新")
    assert p["title"] == "期初餘額 台新" and p["total"] == "169,380"
    opening = lg.commit("存 169380 期初 @台新")
    lg.commit("收入 47823 薪資 @台新 2026-09-16")  # last month's salary: already in the balance
    assert bal(lg, "台新") == "169,380" and repo.get_tx(lg.db, opening).amount == D(121557)
    lg.commit("支出 2000 餐飲 @台新 2026-09-20")  # an old expense is added back
    assert bal(lg, "台新") == "169,380"
    lg.commit("支出 500 餐飲 @台新")  # today, after the opening: counts as usual
    assert bal(lg, "台新") == "168,880"
    assert finance.month_report(lg, "2026-09")["income"] == "47,823"
    assert lg.tx_line(opening) == "存 169380 期初 2026-10-11 @台新"
    assert "已含之前記的 45,823" in lg.preview("存 169380 期初 @台新", opening)["parts"]
    row = next(r for r in lg.state()["transactions"] if r["id"] == opening)
    assert row["label"] == "期初餘額" and row["amount"] == "169,380"
    lg.delete(next(t.id for t in repo.list_txs(lg.db) if t.kind == "income"))
    assert bal(lg, "台新") == "168,880" and repo.get_tx(lg.db, opening).amount == D(171380)


def test_existing_first_deposit_is_converted_once(tmp_path):
    db = Db(tmp_path / "x.db")
    lg = Ledger(db, httpx.Client(transport=httpx.MockTransport(no_http)), today=lambda: TODAY)
    lg.save_account({"name": "台新", "type": "bank"})
    repo.set_setting(db, "openings_converted", "")  # data from before this version
    first = lg.commit("存 169380 @台新")
    lg.commit("存 1000 @台新")  # a later top-up stays a plain deposit
    lg.commit("收入 47823 薪資 @台新 2026-09-16")  # backfilled after the balance was entered
    assert bal(lg, "台新") == "218,203"  # double counted
    lg = Ledger(db, httpx.Client(transport=httpx.MockTransport(no_http)), today=lambda: TODAY)
    assert repo.get_tx(db, first).balance == D(169380) and bal(lg, "台新") == "170,380"
    Ledger(db, httpx.Client(transport=httpx.MockTransport(no_http)), today=lambda: TODAY)
    assert bal(lg, "台新") == "170,380"


# ── 定期定額 ──

from datetime import datetime, timezone  # noqa: E402

from portfolio_ledger.models import Security  # noqa: E402


def yahoo_bars(request: httpx.Request) -> httpx.Response:
    """0050.TW daily bars for 10/05 only (what the local table is missing)."""
    if "0050.TW" not in str(request.url):
        return no_http(request)
    ts = int(datetime(2026, 10, 5, 1, tzinfo=timezone.utc).timestamp())
    return httpx.Response(200, json={"chart": {"result": [{"meta": {"gmtoffset": 28800, "instrumentType": "ETF"},
                          "timestamp": [ts], "indicators": {"quote": [{"close": [110.5]}]}}]}})  # fmt: skip


@pytest.fixture
def broker(clock):
    lg = Ledger(Db(":memory:"), httpx.Client(transport=httpx.MockTransport(yahoo_bars)), today=clock)
    lg.save_account({"name": "國泰", "type": "broker_tw", "fee_discount": "0.28", "fee_min": "1"})
    repo.upsert_securities(lg.db, [Security("0050", "元大台灣50", "TWSE", "TWD", "etf", D("115.2"), D(115), "2026-10-09")])
    repo.put_prices(lg.db, [("0050", "2026-10-06", D("115.2")), ("0050", "2026-10-09", D("116"))])
    lg.commit("存 100000 期初 @國泰 2026-10-01")
    return lg


def test_dca_buys_the_amount_at_that_days_close(broker):
    p = broker.preview("定額 0050 10000 2026-10-06")
    assert p["title"] == "買進 元大台灣50 0050" and "定期定額 10,000，2026-10-06 收盤價" in p["parts"]
    tx = repo.get_tx(broker.db, broker.commit("定額 0050 10000 2026-10-06"))
    assert (tx.kind, tx.date, tx.qty, tx.price, tx.fee) == ("buy", "2026-10-06", D(86), D("115.2"), D(3))
    assert tx.amount == D(-9910) and tx.note == "定期定額"  # 86 × 115.2 = 9,907 + fee 3
    assert broker.tx_line(tx.id) == "買 0050 86 115.2 2026-10-06 @國泰 # 定期定額"


def test_dca_rolls_to_the_next_trading_day_and_fills_gaps(broker):
    tx = repo.get_tx(broker.db, broker.commit("定額 0050 10000 2026-10-05"))  # not stored: from Yahoo
    assert (tx.date, tx.price, tx.qty) == ("2026-10-05", D("110.5"), D(90))
    tx = repo.get_tx(broker.db, broker.commit("定額 0050 10000 2026-10-07"))  # no close 10/07–08 → 10/09
    assert (tx.date, tx.price, tx.qty) == ("2026-10-09", D(116), D(86))


def test_recurring_dca_waits_for_the_close(broker, clock):
    assert recurring.save(broker, {"line": "定額 0050 10000 @國泰", "start_date": "2026-10-10"}) == 0  # Saturday
    rule = recurring.rows(broker)[0]
    assert rule["error"] is None and rule["next_date"] == "2026-10-10" and rule["amount"] == "−10,000"
    clock.d = date(2026, 10, 13)
    repo.put_prices(broker.db, [("0050", "2026-10-12", D(117))])
    assert recurring.run_due(broker) == 1
    tx = next(t for t in repo.list_txs(broker.db) if t.recurring_id)
    assert (tx.date, tx.price, tx.qty) == ("2026-10-12", D(117), D(85))
    assert recurring.run_due(broker) == 0 and recurring.rows(broker)[0]["next_date"] == "2026-11-10"


def test_dca_rule_cannot_repeat_what_a_backfill_already_holds(broker):
    broker.commit("補 0050 1000 100 @國泰 2026-10-06")
    with pytest.raises(EntryError, match="0050 在 2026-10-06 有補登持股"):
        recurring.save(broker, {"line": "定額 0050 10000 @國泰", "start_date": "2026-10-06"})
    assert recurring.rows(broker) == []
    # From the next deduction on is fine.
    assert recurring.save(broker, {"line": "定額 0050 10000 @國泰", "start_date": "2026-10-09"}) == 1


def test_composer_dca_with_repeat_makes_a_rule(broker, clock):
    api = Api(broker, lambda: None)
    r = api.commit("定額 0050 10000 @國泰 2026-10-06", None, "monthly")
    assert r["ok"] and r["posted"] == 1
    rule = recurring.rows(broker)[0]
    assert rule["kind"] == "dca" and rule["start_date"] == "2026-10-06" and rule["next_date"] == "2026-11-06"
    # Before that day's close: the rule is saved and posts once the close is out.
    clock.d = date(2026, 10, 13)
    r = api.commit("定額 0050 5000 @國泰 2026-10-13", None, "monthly")
    assert r["ok"] and r["posted"] == 0 and len(recurring.rows(broker)) == 2
    clock.d = date(2026, 10, 14)
    repo.put_prices(broker.db, [("0050", "2026-10-13", D(118))])
    assert recurring.run_due(broker) == 1


def test_one_off_dca_before_the_close_says_so(broker, clock):
    clock.d = date(2026, 10, 13)
    r = Api(broker, lambda: None).commit("定額 0050 10000 2026-10-13")
    assert not r["ok"] and "2026-10-13 的收盤價還沒出來" in r["error"] and "每月重複" in r["error"]


def test_holding_shows_its_dca(broker):
    recurring.save(broker, {"line": "定額 0050 10000 @國泰", "start_date": "2026-10-06"})
    st = broker.state()
    dca = st["holdings"][0]["dca"]
    assert (dca["count"], dca["first_date"], dca["invested"], dca["avg_price"]) == (1, "2026-10-06", "9,910", "115.20")
    assert dca["rules"][0]["amount"] == "10,000" and dca["rules"][0]["next_date"] == "2026-11-06"
    assert next(t for t in st["transactions"] if t["kind"] == "buy")["dca"]
    broker.commit("買 0050 100 116 @國泰 2026-10-09")
    assert broker.state()["holdings"][0]["dca"]["count"] == 1  # a manual buy is not part of it


def test_editing_a_dca_buy_to_the_fill_marks_it_confirmed(broker):
    recurring.save(broker, {"line": "定額 0050 10000 @國泰", "start_date": "2026-10-06"})
    tx = next(t for t in repo.list_txs(broker.db) if t.recurring_id)
    broker.commit("買 0050 86 115.15 2026-10-06 @國泰 # 定期定額", tx.id)
    edited = repo.get_tx(broker.db, tx.id)
    assert edited.note == DCA_CONFIRMED and edited.recurring_id == tx.recurring_id
    assert broker.state()["holdings"][0]["dca"]["count"] == 1


def test_recurring_adopts_an_entry_recorded_by_hand(lg):
    manual = lg.commit("支出 630 數碼 @台新 2026-09-26 # Claude")
    assert recurring.save(lg, {"line": "支出 630 數碼 @台新 # Claude", "start_date": "2026-09-26"}) == 0
    claude = [t for t in repo.list_txs(lg.db) if t.note == "Claude"]
    assert [t.id for t in claude] == [manual] and claude[0].recurring_id is not None
    # A different amount that day is not the same entry: the rule posts its own.
    lg.commit("支出 99 數碼 @台新 2026-09-26 # 其他")
    assert recurring.save(lg, {"line": "支出 99 數碼 @台新 # 其他月費", "start_date": "2026-09-26"}) == 1


def test_credit_card_opening_is_a_debt(clock):
    lg = Ledger(Db(":memory:"), httpx.Client(transport=httpx.MockTransport(no_http)), today=clock)
    lg.save_account({"name": "玉山", "type": "credit"})
    p = lg.preview("存 -2040 期初 @玉山")
    assert p["title"] == "期初欠款 玉山" and p["total"] == "−2,040"
    opening = lg.commit("存 -2040 期初 @玉山")
    lg.commit("支出 699 運動 @玉山 2026-09-18")  # already in what is owed
    assert bal(lg, "玉山") == "−2,040"
    lg.commit("支出 100 餐飲 @玉山")  # today: adds to it
    assert bal(lg, "玉山") == "−2,140"
    assert lg.tx_line(opening) == "存 -2040 期初 2026-10-11 @玉山"
    assert lg.tx_fields(opening)["amount"] == "-2040"


def test_same_day_entries_recorded_before_the_opening_are_in_it(clock):
    lg = Ledger(Db(":memory:"), httpx.Client(transport=httpx.MockTransport(no_http)), today=clock)
    lg.save_account({"name": "玉山", "type": "credit"})
    lg.commit("支出 30 數碼 @玉山 # iCloud")  # today, recorded first: already in what is owed
    opening = lg.commit("存 -2040 期初 @玉山")
    assert bal(lg, "玉山") == "−2,040"
    lg.commit("支出 100 餐飲 @玉山")  # today, recorded after the opening
    assert bal(lg, "玉山") == "−2,140"
    lg.commit("存 -2040 期初 @玉山", edit_id=opening)  # editing keeps its place
    assert bal(lg, "玉山") == "−2,140"


def test_recurring_rows_monthly_figures(lg):
    recurring.save(lg, {"line": "支出 15000 居住 @台新 # 房租", "freq": "monthly", "start_date": "2026-10-20"})
    recurring.save(lg, {"line": "支出 300 餐飲 # 早餐", "freq": "weekly", "start_date": "2026-10-20"})
    recurring.save(lg, {"line": "收入 120000 獎金", "freq": "yearly", "start_date": "2026-12-20"})
    recurring.save(lg, {"line": "支出 390 # Netflix", "freq": "monthly", "start_date": "2026-10-20", "active": False})
    by = {r["title"]: r for r in recurring.rows(lg)}
    assert by["房租"]["monthly"] == pytest.approx(15000) and by["房租"]["category"] == "居住"
    assert by["早餐"]["monthly"] == pytest.approx(1300)  # 300 × 52 ÷ 12
    bonus = next(r for r in by.values() if r["kind"] == "income")
    assert bonus["monthly"] == pytest.approx(10000) and bonus["category"] == "獎金"
    assert by["Netflix"]["monthly"] is None and by["Netflix"]["category"] == "其他"  # paused
