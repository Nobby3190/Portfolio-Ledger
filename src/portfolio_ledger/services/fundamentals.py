"""財報快照: yearly ratios from public statements and ai-berkshire's 7 去劣 checks (quality-screen).
Pure functions. It lists numbers and which checks fail; it never says buy or sell (DESIGN.md「v1.4」).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

YEARS = 5
FIELDS = ("revenue", "gross_profit", "ebit", "net_income", "eps", "equity", "shares", "ocf", "capex", "interest")


def _div(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return a / b if a is not None and b else None


def ratios(year: dict[str, Decimal]) -> dict[str, Decimal | None]:
    g = year.get
    ocf, capex = g("ocf"), g("capex")
    return {
        "gross_margin": _div(g("gross_profit"), g("revenue")),
        "net_margin": _div(g("net_income"), g("revenue")),
        "roe": _div(g("net_income"), g("equity")),
        "fcf": ocf - capex if ocf is not None and capex is not None else None,
        "ocf_ni": _div(ocf, g("net_income")),
        "coverage": _div(g("ebit"), g("interest")),
    }


def _check(key: str, label: str, rule: str, value: str | None, ok: bool | None, note: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "rule": rule, "value": value, "status": "na" if ok is None else "pass" if ok else "fail", "note": note}


def _pct(x: Decimal) -> str:
    return f"{x * 100:.1f}%"


def checks(annual: dict[str, dict[str, Decimal]], unit: Decimal = Decimal(1), unit_label: str = "") -> list[dict[str, Any]]:
    """The 7 checks over the last YEARS complete years. Missing data is 「資料不足」, never a fail.
    Money is shown in `unit` (the table's: 億, 百萬)."""
    years = sorted(annual)[-YEARS:]
    rows = [annual[y] for y in years]
    n = len(rows)
    span = f"近 {n} 年"

    def series(field: str) -> list[Decimal]:
        return [r[field] for r in rows if r.get(field) is not None]

    out = []
    # 1 平均 ROE
    roes = [x for r in rows if (x := ratios(r)["roe"]) is not None]
    avg = sum(roes, Decimal(0)) / len(roes) if roes else None
    out.append(_check("roe", f"平均 ROE（{span}）", "< 8% 沒過", _pct(avg) if avg is not None else None,
                      None if avg is None or len(roes) < 2 else avg >= Decimal("0.08")))  # fmt: skip
    # 2 自由現金流合計
    fcfs = [x for r in rows if (x := ratios(r)["fcf"]) is not None]
    total = sum(fcfs, Decimal(0)) if fcfs else None
    out.append(_check("fcf", f"自由現金流合計（{span}）", "< 0 沒過", None if total is None else f"{total / unit:,.0f} {unit_label}".strip(),
                      None if total is None or len(fcfs) < 2 else total >= 0))  # fmt: skip
    # 3 利息覆蓋倍數: the latest year that reports interest
    cov = next(((y, c) for y, r in zip(reversed(years), reversed(rows)) if (c := ratios(r)["coverage"]) is not None), None)
    if cov is not None:
        out.append(_check("coverage", "利息覆蓋倍數（EBIT ÷ 利息）", "< 2 倍沒過", f"{cov[1]:,.1f} 倍（{cov[0]}）", cov[1] >= 2))
    elif series("ebit"):
        out.append(_check("coverage", "利息覆蓋倍數（EBIT ÷ 利息）", "< 2 倍沒過", "沒有列出利息費用", True))
    else:
        out.append(_check("coverage", "利息覆蓋倍數（EBIT ÷ 利息）", "< 2 倍沒過", None, None, "銀行、保險不適用"))
    # 4 平均毛利率 (sum ÷ sum: one odd year doesn't dominate)
    gp, rev = series("gross_profit"), [r["revenue"] for r in rows if r.get("gross_profit") is not None]
    gm = _div(sum(gp, Decimal(0)), sum(rev, Decimal(0))) if len(gp) >= 2 else None
    out.append(_check("gross_margin", f"平均毛利率（{span}）", "< 15% 沒過", _pct(gm) if gm is not None else None,
                      None if gm is None else gm >= Decimal("0.15"), "" if gm is not None else "銀行、保險不適用"))  # fmt: skip
    # 5 營業現金流 ÷ 淨利
    both = [(r["ocf"], r["net_income"]) for r in rows if r.get("ocf") is not None and r.get("net_income") is not None]
    q = _div(sum((a for a, _ in both), Decimal(0)), sum((b for _, b in both), Decimal(0))) if len(both) >= 2 else None
    out.append(_check("ocf_ni", f"營業現金流 ÷ 淨利（{span}）", "< 0.7 沒過", f"{q:.2f}" if q is not None else None,
                      None if q is None else q >= Decimal("0.7")))  # fmt: skip
    # 6 平均淨利率
    ni = [(r["net_income"], r["revenue"]) for r in rows if r.get("net_income") is not None]
    nm = _div(sum((a for a, _ in ni), Decimal(0)), sum((b for _, b in ni), Decimal(0))) if len(ni) >= 2 else None
    out.append(_check("net_margin", f"平均淨利率（{span}）", "< 5% 沒過", _pct(nm) if nm is not None else None,
                      None if nm is None else nm >= Decimal("0.05")))  # fmt: skip
    # 7 股數膨脹
    sh = [(y, r["shares"]) for y, r in zip(years, rows) if r.get("shares")]
    if len(sh) >= 2:
        growth = sh[-1][1] / sh[0][1] - 1
        out.append(_check("shares", f"流通股數變化（{sh[0][0]}→{sh[-1][0]}）", "增加 > 20% 沒過",
                          f"{'+' if growth > 0 else '−' if growth < 0 else ''}{abs(growth) * 100:.1f}%", growth <= Decimal("0.2"),
                          "併購增資造成的不算，要自己看"))  # fmt: skip
    else:
        out.append(_check("shares", "流通股數變化", "增加 > 20% 沒過", None, None))
    return out


def table(annual: dict[str, dict[str, Decimal]], unit: Decimal) -> dict[str, Any]:
    """Display rows for the last YEARS years; money in `unit` (億 for TWD, 百萬 for the rest)."""
    years = sorted(annual)[-YEARS:]

    def money(x: Decimal | None) -> str | None:
        return None if x is None else f"{x / unit:,.0f}"

    def pct(x: Decimal | None) -> str | None:
        return None if x is None else _pct(x)

    rows = []
    for key, label, fn in (
        ("revenue", "營收", lambda r, q: money(r.get("revenue"))),
        ("gross_margin", "毛利率", lambda r, q: pct(q["gross_margin"])),
        ("net_margin", "淨利率", lambda r, q: pct(q["net_margin"])),
        ("roe", "ROE", lambda r, q: pct(q["roe"])),
        ("eps", "EPS", lambda r, q: None if r.get("eps") is None else f"{r['eps']:,.2f}"),
        ("ocf_ni", "營業現金流 ÷ 淨利", lambda r, q: None if q["ocf_ni"] is None else f"{q['ocf_ni']:.2f}"),
        ("fcf", "自由現金流", lambda r, q: money(q["fcf"])),
        ("coverage", "利息覆蓋倍數", lambda r, q: None if q["coverage"] is None else f"{q['coverage']:,.1f}"),
        ("shares", "流通股數（百萬）", lambda r, q: None if r.get("shares") is None else f"{r['shares'] / Decimal(1_000_000):,.0f}"),
    ):
        rows.append({"key": key, "label": label, "values": [fn(annual[y], ratios(annual[y])) for y in years]})
    return {"years": years, "rows": rows}
