from datetime import date
from decimal import Decimal as D

import pytest

from portfolio_ledger import repo
from portfolio_ledger.services import alerts, tracking
from portfolio_ledger.services.alerts import Target
from portfolio_ledger.services.finance import FinanceError
from test_dividends import ledger  # noqa: F401  (same fixture: TWSE, TPEx, TWT48U, USD, VOO)

TODAY = date(2026, 10, 11)


def target(**kw) -> Target:
    base = dict(symbol="2330", name="台積電", held=True, currency="TWD", close=D(1000), close_date="2026-10-08",
                prev_close=D(1000), week_ago=D(1000))  # fmt: skip
    return Target(**{**base, **kw})


def keys(items):
    return [a["key"].split(":")[0] for a in items]


def test_moves_and_thresholds():
    day = alerts.check([target(prev_close=D(1060))], TODAY)  # −5.66%
    assert keys(day) == ["day"] and day[0]["title"] == "台積電 跌 5.7%"
    assert alerts.check([target(prev_close=D(1040))], TODAY) == []  # −3.8%
    week = alerts.check([target(week_ago=D(880))], TODAY)  # +13.6%
    assert keys(week) == ["week"] and week[0]["level"] == "warn"
    assert alerts.check([target(week_ago=D(880))], TODAY, {"week_pct": 15}) == []


def test_red_lines_attached_to_moves_only_when_held():
    a = alerts.check([target(prev_close=D(1100), red_lines=["毛利率跌破 50%"])], TODAY)[0]
    assert a["red_lines"] == ["毛利率跌破 50%"] and a["action"] == ["回去看你當初為什麼買"]
    w = alerts.check([target(prev_close=D(1100), held=False, red_lines=["x"])], TODAY)[0]
    assert w["action"] is None


def test_band_review_and_exdividend():
    items = alerts.check([target(band_low=D(1050), review_due="2026-10-01", ex_dividend=("2026-10-15", D(5), D(5000)))], TODAY)
    assert keys(items) == ["low", "review", "exdiv"]
    assert items[1]["kind"] == "review"
    assert {"m": "5,000"} in items[2]["detail"]
    assert alerts.check([target(band_high=D(990))], TODAY)[0]["title"] == "台積電 高於合理價上限"
    assert alerts.check([target(review_due="2026-10-12")], TODAY) == []  # not due yet


def test_watchlist_switch():
    t = target(held=False, prev_close=D(1100))
    assert alerts.check([t], TODAY, {"watchlist": False}) == []


def test_add_months():
    assert tracking.add_months("2026-01-31", 1) == "2026-02-28"
    assert tracking.add_months("2026-11-15", 3) == "2027-02-15"


def test_note_validation_and_round_trip(ledger):  # noqa: F811
    with pytest.raises(FinanceError, match="200 字內"):
        tracking.save_note(ledger, {"symbol": "2330", "thesis": "字" * 201})
    with pytest.raises(FinanceError, match="下限比上限還高"):
        tracking.save_note(ledger, {"symbol": "2330", "band_low": "1200", "band_high": "1000"})
    tracking.save_note(ledger, {"symbol": "2330", "thesis": "先進製程領先", "red_lines": "毛利率 < 50%\n\n 創辦人離職 ",
                                "band_low": "９００", "band_high": "1,200", "review_months": "3"})  # fmt: skip
    n = tracking.get_note(ledger, "2330")
    assert n["red_lines"] == ["毛利率 < 50%", "創辦人離職"]
    assert (n["band_low"], n["band_high"]) == ("900.00", "1,200.00")
    assert n["review_due"] == "2027-01-11"  # 3 months from the day it was written
    assert n["input"]["band_high"] == "1200"
    tracking.mark_reviewed(ledger, "2330")
    assert tracking.get_note(ledger, "2330")["last_review"] == "2026-10-11"
    tracking.save_note(ledger, {"symbol": "2330"})  # emptied
    assert tracking.get_note(ledger, "2330") is None


def test_watchlist_rows_and_rules(ledger):  # noqa: F811
    ledger.commit("存 2000000 @永豐")
    ledger.commit("買 2330 1000 1050")
    with pytest.raises(FinanceError, match="已在持股裡"):
        tracking.add_watch(ledger, "2330")
    assert tracking.add_watch(ledger, "0050") == "0050"
    tracking.save_note(ledger, {"symbol": "0050", "band_low": "190"})
    rows = tracking.watchlist(ledger)
    assert [r["symbol"] for r in rows] == ["0050"]
    r = rows[0]
    assert r["band"] == "≥ 190.00" and r["band_side"] == (-1 if D(r["close"].replace(",", "")) < 190 else 0)
    tracking.remove_watch(ledger, "0050")
    assert tracking.watchlist(ledger) == []


def test_week_change_from_stored_prices(ledger):  # noqa: F811
    repo.put_prices(ledger.db, [("2330", f"2026-10-0{d}", D(1000 + d * 10)) for d in range(1, 9)])
    assert tracking.week_ago(ledger, "2330", "2026-10-08") == D(1030)  # the 3rd: 5 trading days before the 8th
    assert tracking.week_ago(ledger, "2330", "2026-10-03") is None  # not enough history


def test_alerts_report_and_dismiss(ledger):  # noqa: F811
    ledger.commit("存 2000000 @永豐")
    ledger.commit("買 2330 1000 1050")
    # fixture: 2330 closed 2,550 from 2,585 (−1.4%): no move; 除息 10/20 is 9 days away: not yet
    r = tracking.alerts_report(ledger)
    assert r["items"] == [] and r["settings"]["day_pct"] == "5"
    tracking.save_note(ledger, {"symbol": "2330", "band_high": "2000"})
    r = tracking.alerts_report(ledger)
    assert keys(r["items"]) == ["high"]
    tracking.dismiss_alert(ledger, r["items"][0]["key"])
    assert tracking.alerts_report(ledger)["items"] == []
    tracking.save_alert_settings(ledger, {"day_pct": "1"})
    assert keys(tracking.alerts_report(ledger)["items"]) == ["day"]
    with pytest.raises(FinanceError):
        tracking.save_alert_settings(ledger, {"day_pct": "0"})
