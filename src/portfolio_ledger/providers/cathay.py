"""國泰世華 posted FX rates (牌告匯率). The page is server-rendered HTML; we read the 即期匯率 row
(bank buy / bank sell) of each currency block. Used to value foreign cash the way the 國泰 app does."""

from __future__ import annotations

import html as html_lib
import re
import ssl
from dataclasses import dataclass
from decimal import Decimal

import certifi
import httpx

from .base import ProviderError

BOARD_URL = "https://www.cathaybk.com.tw/cathaybk/personal/product/deposit/currency-billboard/"

_BLOCK = re.compile(
    r"\|\s*[^|]*?([A-Z]{3})\s*\|歷史走勢\|.*?即期匯率\|([\d.]+)\|([\d.]+)\|",
)
_TIME = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*\d{1,2}:\d{2}")


@dataclass
class BoardRate:
    currency: str
    buy: Decimal  # bank buys foreign currency from you (what your foreign cash is worth in TWD)
    sell: Decimal  # bank sells it to you (what buying foreign currency costs)


def _text(page: str) -> str:
    page = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    page = html_lib.unescape(re.sub(r"<[^>]+>", "|", page))
    page = re.sub(r"\s+", " ", page)
    return re.sub(r"\|[\s|]*\|", "|", page)


def parse_board(page: str) -> tuple[str, dict[str, BoardRate]]:
    """(board date YYYY-MM-DD, {currency: rates})."""
    text = _text(page)
    m = _TIME.search(text[text.find("Board time") :] if "Board time" in text else text)
    if not m:
        raise ProviderError("國泰匯率：找不到掛牌時間")
    y, mo, d = map(int, m.groups())
    rates: dict[str, BoardRate] = {}
    for b in _BLOCK.finditer(text):
        cur = b.group(1)
        if cur not in rates:
            rates[cur] = BoardRate(cur, Decimal(b.group(2)), Decimal(b.group(3)))
    if not rates:
        raise ProviderError("國泰匯率：頁面格式改了，讀不到匯率")
    return f"{y:04d}-{mo:02d}-{d:02d}", rates


def _tls() -> ssl.SSLContext:
    """Full certificate verification (trusted CA, hostname, expiry) without Python 3.13's
    VERIFY_X509_STRICT: 國泰世華's chain lacks a Subject Key Identifier, which only strict mode rejects."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


_client: httpx.Client | None = None


def fetch_board(client: httpx.Client | None = None) -> tuple[str, dict[str, BoardRate]]:
    """`client` is for tests; normally a dedicated client with the relaxed TLS context is used."""
    global _client
    if client is None:
        if _client is None:
            _client = httpx.Client(verify=_tls(), timeout=20.0, headers={"User-Agent": "Mozilla/5.0"})
        client = _client
    try:
        resp = client.get(BOARD_URL)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise ProviderError(f"國泰匯率下載失敗：{e}") from e
    return parse_board(resp.text)
