"""Shared bits for quote providers: one HTTP client, number and date parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class ProviderError(RuntimeError):
    pass


@dataclass
class History:
    """A symbol's recent daily closes, newest last."""

    symbol: str
    name: str
    currency: str
    kind: str
    closes: list[tuple[str, Decimal]]  # (YYYY-MM-DD, close)

    @property
    def last(self) -> tuple[str, Decimal] | None:
        return self.closes[-1] if self.closes else None

    @property
    def prev_close(self) -> Decimal | None:
        return self.closes[-2][1] if len(self.closes) > 1 else None


def make_client() -> httpx.Client:
    # Yahoo rejects requests without a browser-like User-Agent; the TW exchanges don't care.
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)


def dec(v: object) -> Decimal | None:
    """Exchange feeds use '', '--', '---' or '除權息' for no value; strip commas and spaces."""
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


_ROC = re.compile(r"^(\d{2,3})(\d{2})(\d{2})$")


def roc_date(s: str) -> str | None:
    """'1151008' (ROC year 115) -> '2026-10-08'."""
    m = _ROC.match(s.strip())
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{int(y) + 1911:04d}-{mo}-{d}"
