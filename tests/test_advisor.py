from portfolio_ledger.services import advisor
from portfolio_ledger.services.advisor import Deposit, Holding, Inputs, Need


def levels(i: Inputs, **t) -> dict[str, str]:
    return {a["key"]: a["level"] for a in advisor.check(i, t)}


def base(**kw) -> Inputs:
    return Inputs(**{"liquid": 300_000, "cash_and_deposits": 300_000, "monthly_spend": 40_000,
                     "monthly_income": 80_000, "monthly_net": 40_000, **kw})


def test_emergency_fund_bounds():
    assert levels(base(liquid=200_000))["fund"] == "warn"  # 5 months
    assert levels(base(liquid=240_000))["fund"] == "ok"  # exactly 6
    assert levels(base(liquid=600_000))["fund"] == "note"  # 15 months: idle cash
    assert "fund" not in levels(base(monthly_spend=None))  # no data, no guess


def test_fund_action_amount_is_a_money_segment():
    fund = next(a for a in advisor.check(base(liquid=200_000)) if a["key"] == "fund")
    assert {"m": "40,000"} in fund["action"]


def test_drift_threshold():
    assert levels(base(drift=[("股票", 0.76, 0.70, -60_000)]))["drift"] == "note"
    assert levels(base(drift=[("股票", 0.74, 0.70, -40_000)]))["drift"] == "ok"


def test_single_stock_concentration_ignores_etfs():
    h = [Holding("台積電", 400_000, False), Holding("0050", 600_000, True)]
    assert levels(base(holdings=h))["stock"] == "warn"  # 40%
    h[0].value = 250_000  # 29%
    assert levels(base(holdings=h))["stock"] == "note"
    assert levels(base(holdings=h), stock_note_pct=30)["stock"] == "ok"
    assert "stock" not in levels(base(holdings=[Holding("0050", 1, True)]))


def test_near_needs_against_cash():
    need = [Need("買車", "2027-06", 400_000)]
    assert levels(base(needs=need))["near"] == "warn"
    assert levels(base(needs=need, cash_and_deposits=500_000))["near"] == "ok"


def test_loan_burden():
    assert levels(base(loan_payment=36_000, loan_plans=["買房"]))["loan"] == "warn"  # 45%
    assert levels(base(loan_payment=28_000, loan_plans=["買房"]))["loan"] == "note"  # 35%
    assert levels(base(loan_payment=20_000, loan_plans=["買房"]))["loan"] == "ok"
    assert "loan" not in levels(base(loan_payment=20_000, monthly_income=None))


def test_savings_rate_and_deposits_and_order():
    items = advisor.check(base(monthly_net=4_000, liquid=100_000, deposits=[Deposit("一年定存", 12)]))
    assert [a["level"] for a in items] == sorted((a["level"] for a in items), key=advisor.LEVELS.get)
    got = {a["key"]: a["level"] for a in items}
    assert got["savings"] == "note" and got["deposit"] == "note" and got["fund"] == "warn"
    assert "deposit" not in levels(base(deposits=[Deposit("一年定存", 90)]))
