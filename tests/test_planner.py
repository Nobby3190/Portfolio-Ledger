from datetime import date

import pytest

from portfolio_ledger.services import planner
from portfolio_ledger.services.planner import dca, fire, months_between, rebalance, xirr


def test_fire_target_and_years():
    r = fire(current=1_000_000, monthly=30_000, annual_return=0.06, inflation=0.02, annual_spend=600_000,
             withdrawal_rate=0.04)
    assert r.target == pytest.approx(15_000_000)
    assert r.months_to_target is not None and 20 * 12 < r.months_to_target < 24 * 12  # 3.9% real return
    assert r.series[0] == (0, 1_000_000)


def test_fire_already_there_and_never():
    assert fire(20e6, 0, 0.05, 0.02, 600_000, 0.04).months_to_target == 0
    assert fire(0, 0, 0.05, 0.02, 600_000, 0.04).months_to_target is None


def test_rebalance_trades_sum_to_zero():
    rows = {r.label: r for r in rebalance({"股票": 800, "債券": 100, "現金": 100}, {"股票": 70, "債券": 20, "現金": 10})}
    assert rows["股票"].trade == pytest.approx(-100)
    assert rows["債券"].trade == pytest.approx(100)
    assert sum(r.trade for r in rows.values()) == pytest.approx(0)


def test_xirr_simple_year():
    assert xirr([(date(2025, 1, 1), -100), (date(2026, 1, 1), 110)]) == pytest.approx(0.10, abs=1e-4)
    assert xirr([(date(2025, 1, 1), 100)]) is None


def test_dca_flat_price():
    bt = dca([("2026-01-01", 10.0), ("2026-02-01", 10.0), ("2026-03-01", 20.0)], 100, date(2026, 3, 15))
    assert bt.invested == 300 and bt.shares == pytest.approx(25) and bt.value == pytest.approx(500)
    assert bt.xirr is not None and bt.xirr > 0


def test_months_between():
    assert months_between(date(2026, 10, 11), date(2027, 10, 11)) == 12
    assert months_between(date(2026, 10, 11), date(2026, 10, 1)) == 0


def test_amortize_matches_bank_calculator():
    loan = planner.amortize(10_000_000, 0.022, 30)
    assert loan.payment == pytest.approx(37_969, abs=2)  # 本息平均攤還, 1,000 萬 2.2% 30 年
    assert loan.grace_payment == pytest.approx(18_333, abs=1) and loan.grace_months == 0
    assert loan.total_interest == pytest.approx(loan.payment * 360 - 10_000_000)
    assert loan.at(0) == 0 and loan.at(361) == 0


def test_amortize_grace_period_is_interest_only():
    loan = planner.amortize(10_000_000, 0.022, 30, grace_years=3)
    assert loan.grace_months == 36 and loan.at(36) == pytest.approx(18_333, abs=1)
    assert loan.at(37) > planner.amortize(10_000_000, 0.022, 30).payment  # shorter repayment
    assert planner.amortize(1_200, 0, 1).payment == pytest.approx(100)


def test_fire_events_delay_target():
    base = planner.fire(1_000_000, 30_000, 0.06, 0.02, 600_000, 0.04)
    same = planner.fire(1_000_000, 30_000, 0.06, 0.02, 600_000, 0.04, events=[])
    assert same.months_to_target == base.months_to_target and same.series == base.series
    house = planner.PlanEvent(24, 3_000_000, planner.amortize(12_000_000, 0.022, 30), 3_000)
    r = planner.fire(1_000_000, 30_000, 0.06, 0.02, 600_000, 0.04, events=[house])
    assert r.target == pytest.approx((600_000 + 36_000) / 0.04)
    assert r.months_to_target is None or r.months_to_target > (base.months_to_target or 0)
    assert r.series[2][1] < base.series[2][1] - 3_000_000 * 0.9  # the down payment left in year 2
