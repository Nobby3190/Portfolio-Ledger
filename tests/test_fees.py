from decimal import Decimal as D

from portfolio_ledger.services.fees import tw_fee, tw_kind, tw_tax


def test_fee_truncates_and_applies_discount():
    assert tw_fee(D(1_050_000)) == D(1496)  # 1496.25
    assert tw_fee(D(1_050_000), D("0.6")) == D(897)  # 897.75


def test_fee_minimum():
    assert tw_fee(D(5000)) == D(20)  # 7.125 -> minimum
    assert tw_fee(D(5000), minimum=D(1)) == D(7)
    assert tw_fee(D(0)) == D(0)


def test_tax_by_kind():
    assert tw_tax(D(2_550_000), "stock", "2026-10-08") == D(7650)
    assert tw_tax(D(114_950), "etf", "2026-10-08") == D(114)  # 114.95
    assert tw_tax(D(100_000), "stock", "2026-10-08", daytrade=True) == D(150)


def test_bond_etf_exemption_ends():
    assert tw_tax(D(27_500), "bond_etf", "2026-12-31") == D(0)
    assert tw_tax(D(27_500), "bond_etf", "2027-01-02") == D(27)


def test_kind_from_code():
    assert tw_kind("2330") == "stock"
    assert tw_kind("0050") == "etf"
    assert tw_kind("00400A") == "etf"
    assert tw_kind("00679B") == "bond_etf"


def test_cathay_online_terms():
    # 國泰證券 app/web orders: 2.8折, minimum 1 元
    assert tw_fee(D(2_550_000), D("0.28"), D(1)) == D(1017)  # 1017.45
    assert tw_fee(D(1149), D("0.28"), D(1)) == D(1)  # odd lot: 0.458 -> minimum


def test_hk_fees_cathay_online():
    from portfolio_ledger.services.fees import hk_fees

    # 100 × 424.8 = 42,480 HKD: commission 106.20, levies 5.39 (0.0127%), stamp 42.48 -> 43
    fee, tax = hk_fees(D(42480), "stock")
    assert (fee, tax) == (D("111.59"), D(43))
    # small trade hits the HKD 40 minimum; ETFs pay no stamp duty
    assert hk_fees(D(2484), "etf") == (D("40.32"), D(0))
