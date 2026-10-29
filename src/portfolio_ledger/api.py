"""js_api exposed to the page. Every method returns {ok: true, ...} or {ok: false, error}."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import unlock as auth
from .services import finance, recurring, tracking
from .services.finance import FinanceError
from .services.ledger import EntryError, Ledger, QuoteNotYet
from .services.quick import ParseError, parse

log = logging.getLogger(__name__)


def _call(fn: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
    try:
        return {"ok": True, **(fn() or {})}
    except (EntryError, FinanceError) as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        log.exception("api call failed")
        return {"ok": False, "error": f"發生錯誤：{e}"}


def _is_dca(text: str, today: date) -> bool:
    try:
        return parse(text, today).action == "dca"
    except ParseError:
        return False


class Api:
    # pywebview exposes public attributes too; keep collaborators private.
    def __init__(self, ledger: Ledger, refresh: Callable[[], None]) -> None:
        self._ledger = ledger
        self._refresh = refresh

    def get_state(self) -> dict[str, Any]:
        return _call(lambda: {"state": self._ledger.state()})

    def unlock(self) -> dict[str, Any]:
        """隱藏金額: the system's Touch ID / password prompt; blocks until it closes."""
        try:
            auth.authenticate()
        except auth.Cancelled:
            return {"ok": False, "cancelled": True, "error": ""}
        except auth.UnlockError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            log.exception("unlock failed")
            return {"ok": False, "error": f"發生錯誤：{e}"}
        return {"ok": True}

    def preview(self, text: str, edit_id: int | None = None) -> dict[str, Any]:
        return _call(lambda: {"preview": self._ledger.preview(text, edit_id)})

    def commit(self, text: str, edit_id: int | None = None, repeat: str | None = None) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            dca = _is_dca(text, self._ledger.today())
            if repeat and edit_id is None and dca:
                # A rule rather than a commit: before the close there is no price yet, and the rule waits for it.
                posted = recurring.start_dca(self._ledger, text, repeat)
                return {"id": None, "posted": posted, "state": self._ledger.state()}
            try:
                tx_id = self._ledger.commit(text, edit_id)
            except QuoteNotYet as e:
                if not dca:
                    raise
                raise EntryError(f"{e.day} 的收盤價還沒出來：收盤後再記，或勾「每月重複」讓它收盤後自動記") from e
            if repeat and edit_id is None:  # 記一筆的「每月重複」
                recurring.from_commit(self._ledger, text, tx_id, repeat)
            return {"id": tx_id, "state": self._ledger.state()}

        return _call(run)

    def delete_tx(self, tx_id: int) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            self._ledger.delete(tx_id)
            return {"state": self._ledger.state()}

        return _call(run)

    def tx_line(self, tx_id: int) -> dict[str, Any]:
        return _call(lambda: {"line": self._ledger.tx_line(tx_id)})

    def tx_fields(self, tx_id: int) -> dict[str, Any]:
        return _call(lambda: {"fields": self._ledger.tx_fields(tx_id)})

    def save_account(self, data: dict[str, Any]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            acc_id = self._ledger.save_account(data)
            self._refresh()  # a new currency needs its FX rate
            return {"id": acc_id, "state": self._ledger.state()}

        return _call(run)

    def save_group(self, data: dict[str, Any]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            self._ledger.save_group(data)
            self._refresh()  # new currencies need FX rates
            return {"state": self._ledger.state()}

        return _call(run)

    def delete_group(self, name: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            self._ledger.delete_group(name)
            return {"state": self._ledger.state()}

        return _call(run)

    def delete_account(self, account_id: int) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            self._ledger.delete_account(account_id)
            return {"state": self._ledger.state()}

        return _call(run)

    def save_settings(self, values: dict[str, str]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            self._ledger.save_settings(values)
            return {"state": self._ledger.state()}

        return _call(run)

    # ── 收支 ──

    def get_month(self, month: str | None = None) -> dict[str, Any]:
        return _call(lambda: {"month": finance.month_report(self._ledger, month)})

    def set_budget(self, category_id: int, amount: str, month: str | None = None) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.set_budget(self._ledger, category_id, amount)
            return {"month": finance.month_report(self._ledger, month)}

        return _call(run)

    def set_total_budget(self, amount: str, month: str | None = None) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.set_total_budget(self._ledger, amount)
            return {"month": finance.month_report(self._ledger, month)}

        return _call(run)

    def rename_category(self, category_id: int, name: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.rename_category(self._ledger, category_id, name)
            return {"state": self._ledger.state()}

        return _call(run)

    def set_category_parent(self, category_id: int, parent_id: int | None) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.set_category_parent(self._ledger, category_id, parent_id)
            return {"state": self._ledger.state()}

        return _call(run)

    def add_category(self, kind: str, name: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.add_category(self._ledger, kind, name)
            return {"state": self._ledger.state()}

        return _call(run)

    def set_category_color(self, category_id: int, color: str | None) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.set_category_color(self._ledger, category_id, color)
            return {"state": self._ledger.state()}

        return _call(run)

    def set_category_archived(self, category_id: int, archived: bool) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.set_category_archived(self._ledger, category_id, archived)
            return {"state": self._ledger.state()}

        return _call(run)

    def move_category(self, category_id: int, step: int) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.move_category(self._ledger, category_id, step)
            return {"state": self._ledger.state()}

        return _call(run)

    def delete_category(self, category_id: int) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.delete_category(self._ledger, category_id)
            return {"state": self._ledger.state()}

        return _call(run)

    def get_year(self, year: int | None = None) -> dict[str, Any]:
        return _call(lambda: {"year": finance.year_report(self._ledger, year)})

    # ── 週期性收支 ──

    def get_recurring(self) -> dict[str, Any]:
        return _call(lambda: {"rules": recurring.rows(self._ledger)})

    def recurring_backfill(self, data: dict[str, Any]) -> dict[str, Any]:
        return _call(lambda: {"count": recurring.backfill_count(self._ledger, data)})

    def save_recurring(self, data: dict[str, Any]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            posted = recurring.save(self._ledger, data)
            return {"posted": posted, "rules": recurring.rows(self._ledger), "state": self._ledger.state()}

        return _call(run)

    def delete_recurring(self, rule_id: int) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            recurring.delete(self._ledger, rule_id)
            return {"rules": recurring.rows(self._ledger), "state": self._ledger.state()}

        return _call(run)

    # ── 規劃 ──

    def get_plan(self) -> dict[str, Any]:
        return _call(lambda: {"plan": finance.plan(self._ledger)})

    def save_plan(self, values: dict[str, Any]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.save_plan(self._ledger, values)
            return {"plan": finance.plan(self._ledger)}

        return _call(run)

    def save_targets(self, values: dict[str, Any]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.save_targets(self._ledger, values)
            return {"plan": finance.plan(self._ledger)}

        return _call(run)

    def save_life_plan(self, data: dict[str, Any]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.save_life_plan(self._ledger, data)
            return {"plan": finance.plan(self._ledger)}

        return _call(run)

    def delete_life_plan(self, plan_id: int) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.delete_life_plan(self._ledger, plan_id)
            return {"plan": finance.plan(self._ledger)}

        return _call(run)

    # ── 健檢 ──

    def get_advice(self) -> dict[str, Any]:
        return _call(lambda: {"advice": finance.advice(self._ledger)})

    def save_advice_thresholds(self, values: dict[str, Any]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            finance.save_advice_thresholds(self._ledger, values)
            return {"advice": finance.advice(self._ledger)}

        return _call(run)

    # ── 自選股、投資筆記、價格提醒 ──

    def get_watchlist(self) -> dict[str, Any]:
        return _call(lambda: {"watchlist": tracking.watchlist(self._ledger)})

    def add_watch(self, symbol: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            sym = tracking.add_watch(self._ledger, symbol)
            return {"symbol": sym, "watchlist": tracking.watchlist(self._ledger)}

        return _call(run)

    def remove_watch(self, symbol: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            tracking.remove_watch(self._ledger, symbol)
            return {"watchlist": tracking.watchlist(self._ledger)}

        return _call(run)

    def get_note(self, symbol: str) -> dict[str, Any]:
        return _call(lambda: {"note": tracking.get_note(self._ledger, symbol)})

    def save_note(self, data: dict[str, Any]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            tracking.save_note(self._ledger, data)
            return {"note": tracking.get_note(self._ledger, str(data.get("symbol") or ""))}

        return _call(run)

    def mark_reviewed(self, symbol: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            tracking.mark_reviewed(self._ledger, symbol)
            return {"note": tracking.get_note(self._ledger, symbol)}

        return _call(run)

    def get_alerts(self) -> dict[str, Any]:
        return _call(lambda: {"alerts": tracking.alerts_report(self._ledger)})

    def dismiss_alert(self, key: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            tracking.dismiss_alert(self._ledger, key)
            return {"alerts": tracking.alerts_report(self._ledger)}

        return _call(run)

    def save_alert_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            tracking.save_alert_settings(self._ledger, values)
            return {"alerts": tracking.alerts_report(self._ledger)}

        return _call(run)

    # ── 財報快照、ai-berkshire ──

    def get_fundamentals(self, symbol: str, force: bool = False) -> dict[str, Any]:
        return _call(lambda: {"fundamentals": tracking.fundamentals_report(self._ledger, symbol, force)})

    def copy_text(self, text: str) -> dict[str, Any]:
        def run() -> None:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)

        return _call(run)

    def copy_holdings(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            line = tracking.holdings_line(self._ledger)
            subprocess.run(["pbcopy"], input=line.encode("utf-8"), check=True)
            return {"text": line}

        return _call(run)

    def export_holdings_md(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            dest = Path.home() / "Downloads" / f"Portfolio-Ledger-持倉-{datetime.now():%Y%m%d-%H%M}.md"
            dest.write_text(tracking.holdings_markdown(self._ledger), encoding="utf-8")
            subprocess.run(["open", "-R", str(dest)], check=False)
            return {"path": str(dest)}

        return _call(run)

    # ── 股利 ──

    def get_dividends(self) -> dict[str, Any]:
        return _call(lambda: {"dividends": finance.dividend_report(self._ledger)})

    def refresh(self) -> dict[str, Any]:
        return _call(lambda: self._refresh())

    def export_csv(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            dest = Path.home() / "Downloads" / f"Portfolio-Ledger-交易-{datetime.now():%Y%m%d-%H%M}.csv"
            self._ledger.export_csv(dest)
            subprocess.run(["open", "-R", str(dest)], check=False)
            return {"path": str(dest)}

        return _call(run)

    def backup(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            dest = Path.home() / "Downloads" / f"Portfolio-Ledger-備份-{datetime.now():%Y%m%d-%H%M}.db"
            self._ledger.db.backup_to(dest)
            subprocess.run(["open", "-R", str(dest)], check=False)
            return {"path": str(dest)}

        return _call(run)
