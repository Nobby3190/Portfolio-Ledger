"""Entry point: `uv run portfolio-ledger`."""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import webview

from .api import Api
from .db import APP_DIR, open_app_db
from .poller import Poller
from .services import recurring
from .services.ledger import Ledger

UI = Path(__file__).parent / "ui"  # built by `npm --prefix frontend run build`
log = logging.getLogger(__name__)


class Notifier:
    """Tells the page to reload its state, on its own thread: evaluate_js blocks until WKWebView
    answers, which can take a long time while the view is suspended, and the poller must not wait."""

    def __init__(self, windows: list[webview.Window]) -> None:
        self.windows = windows
        self._pending = threading.Event()
        threading.Thread(target=self._run, name="notifier", daemon=True).start()

    def __call__(self) -> None:
        self._pending.set()

    def _run(self) -> None:
        while True:
            self._pending.wait()
            self._pending.clear()
            for w in self.windows:
                try:
                    w.evaluate_js("window.ledgerChanged && window.ledgerChanged()")
                except Exception:
                    log.exception("notify page failed")


def main() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if getattr(sys, "frozen", False):  # launched from Finder: no terminal, so also log to a file
        APP_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(APP_DIR / "portfolio-ledger.log", maxBytes=1_000_000, backupCount=1))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", handlers=handlers
    )

    ledger = Ledger(open_app_db())
    try:
        recurring.run_due(ledger)  # before the first page load; the poller repeats it on each new day
    except Exception:
        log.exception("recurring entries failed")
    windows: list[webview.Window] = []
    poller = Poller(ledger, Notifier(windows))
    api = Api(ledger, poller.refresh_now)

    # LEDGER_DEV_URL=http://localhost:5175 loads the Vite dev server (hot reload) instead of the build.
    url = os.environ.get("LEDGER_DEV_URL") or str(UI / "index.html")
    if not url.startswith("http") and not (UI / "index.html").exists():
        log.error("找不到前端檔案 %s，請先執行：npm --prefix frontend install && npm --prefix frontend run build", UI)
        raise SystemExit(1)
    windows.append(
        webview.create_window(
            "帳本 Ledger",
            url,
            js_api=api,
            width=1280,
            height=880,
            min_size=(720, 560),
        )
    )
    # The build is ES modules, which WKWebView won't load from file:// — serve it over local HTTP.
    webview.start(poller.start, debug=os.environ.get("LEDGER_DEBUG") == "1", http_server=True)
