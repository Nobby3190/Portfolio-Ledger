"""Background quote refresh: once at launch, then after each market's daily close.

TW closes are published after 14:30 Taipei time on weekdays; US closes after 06:00
Taipei time Tuesday–Saturday. Checking once a minute against those boundaries also
catches up after the Mac wakes from sleep.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, time, timedelta

from .services.ledger import Ledger, taipei_now

TW_READY = time(14, 30)
US_READY = time(6, 0)
log = logging.getLogger(__name__)


def last_boundary(now: datetime, at: time, weekdays: set[int]) -> datetime:
    """The most recent datetime ≤ now at time `at` on one of `weekdays` (Mon=0)."""
    day = now.date()
    for _ in range(8):
        candidate = datetime.combine(day, at, tzinfo=now.tzinfo)
        if candidate <= now and day.weekday() in weekdays:
            return candidate
        day -= timedelta(days=1)
    raise AssertionError("unreachable")


class Poller:
    def __init__(self, ledger: Ledger, on_update: Callable[[], None]) -> None:
        self.ledger = ledger
        self.on_update = on_update
        self._wake = threading.Event()
        self._force = False
        self._last_tw: datetime | None = None
        self._last_us: datetime | None = None

    def start(self) -> None:
        threading.Thread(target=self._run, name="poller", daemon=True).start()

    def refresh_now(self) -> None:
        self._force = True
        self._wake.set()

    def _run(self) -> None:
        while True:
            now = taipei_now()
            force, self._force = self._force, False
            tw = force or self._last_tw is None or self._last_tw < last_boundary(now, TW_READY, {0, 1, 2, 3, 4})
            us = force or self._last_us is None or self._last_us < last_boundary(now, US_READY, {1, 2, 3, 4, 5})
            if tw or us:
                log.info("refreshing quotes (tw=%s us=%s)", tw, us)
                self.ledger.refresh(tw=tw, us=us)
                if tw:
                    self._last_tw = now
                if us:
                    self._last_us = now
                self.on_update()
            self._wake.wait(60)
            self._wake.clear()
