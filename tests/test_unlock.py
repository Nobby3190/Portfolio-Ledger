"""隱藏金額: on by default, and showing the amounts goes through the system prompt (mocked here)."""

from datetime import date

import httpx
import pytest

from portfolio_ledger import repo
from portfolio_ledger import unlock as auth
from portfolio_ledger.api import Api
from portfolio_ledger.db import Db
from portfolio_ledger.services.ledger import Ledger


@pytest.fixture
def api():
    lg = Ledger(Db(":memory:"), httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))), today=lambda: date(2026, 10, 18))
    return Api(lg, lambda: None)


def test_lock_is_on_by_default_even_with_the_old_setting(api):
    repo.set_setting(api._ledger.db, "privacy", "0")  # the old on/off state no longer counts
    assert api._ledger.settings()["privacy_lock"] == "1"
    api._ledger.save_settings({"privacy_lock": "0"})
    assert api._ledger.settings()["privacy_lock"] == "0"


def test_unlock_results(api, monkeypatch):
    monkeypatch.setattr(auth, "authenticate", lambda: None)
    assert api.unlock() == {"ok": True}

    def cancel():
        raise auth.Cancelled

    monkeypatch.setattr(auth, "authenticate", cancel)
    assert api.unlock() == {"ok": False, "cancelled": True, "error": ""}

    def fail():
        raise auth.UnlockError("驗證沒有通過")

    monkeypatch.setattr(auth, "authenticate", fail)
    assert api.unlock() == {"ok": False, "error": "驗證沒有通過"}
