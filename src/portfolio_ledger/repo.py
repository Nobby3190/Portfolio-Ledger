"""SQL access. Functions take a Db and return models; no business rules here."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from .db import Db
from .models import Account, Category, LifePlan, Note, Recurring, Security, Tx


def _d(v: str | None) -> Decimal | None:
    return None if v is None else Decimal(v)


def _s(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


# ── accounts ─────────────────────────────────────────────────────────────


def _account(r: sqlite3.Row) -> Account:
    return Account(
        id=r["id"],
        name=r["name"],
        type=r["type"],
        currency=r["currency"],
        fee_discount=_d(r["fee_discount"]),
        fee_min=_d(r["fee_min"]),
        archived=bool(r["archived"]),
        sort=r["sort"],
        rate=_d(r["rate"]),
        start_date=r["start_date"],
        maturity_date=r["maturity_date"],
        group_name=r["group_name"],
        principal=_d(r["principal"]),
        term_years=_d(r["term_years"]),
        grace_years=_d(r["grace_years"]),
        color=r["color"],
        statement_day=r["statement_day"],
        pay_day=r["pay_day"],
    )


def list_accounts(db: Db, include_archived: bool = False) -> list[Account]:
    where = "" if include_archived else "WHERE archived = 0"
    return [_account(r) for r in db.query(f"SELECT * FROM accounts {where} ORDER BY sort, id")]


def get_account(db: Db, account_id: int) -> Account | None:
    rows = db.query("SELECT * FROM accounts WHERE id = ?", (account_id,))
    return _account(rows[0]) if rows else None


def save_account(db: Db, a: Account) -> int:
    values = (
        a.name, a.type, a.currency, _s(a.fee_discount), _s(a.fee_min), int(a.archived), a.sort,
        _s(a.rate), a.start_date, a.maturity_date, a.group_name, _s(a.principal), _s(a.term_years), _s(a.grace_years),
        a.color, a.statement_day, a.pay_day,
    )  # fmt: skip
    with db.write() as c:
        if a.id is None:
            cur = c.execute(
                "INSERT INTO accounts (name, type, currency, fee_discount, fee_min, archived, sort,"
                " rate, start_date, maturity_date, group_name, principal, term_years, grace_years, color,"
                " statement_day, pay_day) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            return int(cur.lastrowid or 0)
        c.execute(
            "UPDATE accounts SET name=?, type=?, currency=?, fee_discount=?, fee_min=?, archived=?, sort=?,"
            " rate=?, start_date=?, maturity_date=?, group_name=?, principal=?, term_years=?, grace_years=?,"
            " color=?, statement_day=?, pay_day=? WHERE id=?",
            (*values, a.id),
        )
        return a.id


def delete_account(db: Db, account_id: int) -> None:
    with db.write() as c:
        c.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


def account_tx_count(db: Db, account_id: int) -> int:
    return db.query("SELECT COUNT(*) FROM transactions WHERE account_id = ?", (account_id,))[0][0]


# ── securities ───────────────────────────────────────────────────────────


def _security(r: sqlite3.Row) -> Security:
    return Security(
        symbol=r["symbol"],
        name=r["name"],
        market=r["market"],
        currency=r["currency"],
        kind=r["kind"],
        last_close=_d(r["last_close"]),
        prev_close=_d(r["prev_close"]),
        last_date=r["last_date"],
        pe=_d(r["pe"]),
        pb=_d(r["pb"]),
        dividend_yield=_d(r["dividend_yield"]),
    )


def put_valuations(db: Db, rows: Iterable[tuple[str, Decimal | None, Decimal | None, Decimal | None]]) -> None:
    """rows: (symbol, 本益比, 股價淨值比, 殖利率 %)."""
    with db.write() as c:
        c.executemany(
            "UPDATE securities SET pe = ?, pb = ?, dividend_yield = ? WHERE symbol = ?",
            [(_s(pe), _s(pb), _s(y), s) for s, pe, pb, y in rows],
        )


def get_security(db: Db, symbol: str) -> Security | None:
    rows = db.query("SELECT * FROM securities WHERE symbol = ?", (symbol,))
    return _security(rows[0]) if rows else None


def securities(db: Db, symbols: Iterable[str]) -> dict[str, Security]:
    symbols = list(set(symbols))
    if not symbols:
        return {}
    marks = ",".join("?" * len(symbols))
    return {r["symbol"]: _security(r) for r in db.query(f"SELECT * FROM securities WHERE symbol IN ({marks})", tuple(symbols))}


def search_securities(db: Db, q: str, limit: int = 6) -> list[Security]:
    rows = db.query(
        "SELECT * FROM securities WHERE symbol LIKE ? OR name LIKE ?"
        " ORDER BY symbol = ? DESC, length(symbol), symbol LIMIT ?",
        (f"{q}%", f"%{q}%", q.upper(), limit),
    )
    return [_security(r) for r in rows]


def upsert_securities(db: Db, items: Iterable[Security]) -> None:
    """Insert or refresh name and latest close; never wipes a known close with NULL."""
    with db.write() as c:
        c.executemany(
            "INSERT INTO securities (symbol, name, market, currency, kind, last_close, prev_close, last_date)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, market=excluded.market,"
            " currency=excluded.currency, kind=excluded.kind,"
            " last_close=coalesce(excluded.last_close, last_close),"
            " prev_close=coalesce(excluded.prev_close, prev_close),"
            " last_date=coalesce(excluded.last_date, last_date)",
            [
                (s.symbol, s.name, s.market, s.currency, s.kind, _s(s.last_close), _s(s.prev_close), s.last_date)
                for s in items
            ],
        )


def count_tw_securities(db: Db) -> int:
    return db.query("SELECT COUNT(*) FROM securities WHERE market IN ('TWSE', 'TPEX')")[0][0]


# ── transactions ─────────────────────────────────────────────────────────

_TX_COLS = (
    "account_id, date, kind, symbol, qty, price, amount, fee, tax, fx_rate, category_id, transfer_group, note,"
    " recurring_id, balance"
)
_TX_MARKS = ",".join("?" * len(_TX_COLS.split(",")))


def _tx(r: sqlite3.Row) -> Tx:
    return Tx(
        id=r["id"],
        account_id=r["account_id"],
        date=r["date"],
        kind=r["kind"],
        symbol=r["symbol"],
        qty=_d(r["qty"]),
        price=_d(r["price"]),
        amount=Decimal(r["amount"]),
        fee=Decimal(r["fee"]),
        tax=Decimal(r["tax"]),
        fx_rate=_d(r["fx_rate"]),
        category_id=r["category_id"],
        transfer_group=r["transfer_group"],
        note=r["note"],
        recurring_id=r["recurring_id"],
        balance=_d(r["balance"]),
    )


def _tx_values(t: Tx) -> tuple:
    return (
        t.account_id,
        t.date,
        t.kind,
        t.symbol,
        _s(t.qty),
        _s(t.price),
        str(t.amount),
        str(t.fee),
        str(t.tax),
        _s(t.fx_rate),
        t.category_id,
        t.transfer_group,
        t.note,
        t.recurring_id,
        _s(t.balance),
    )


def list_txs(db: Db) -> list[Tx]:
    """Oldest first, in the order they must be replayed. Kept until the next write (one preview or save
    reads them several times): the list is the caller's, the Tx objects are shared and only read."""
    with db.lock:
        if db.txs is None or db.txs[0] != db.version:
            db.txs = (db.version, [_tx(r) for r in db.query("SELECT * FROM transactions ORDER BY date, id")])
        return list(db.txs[1])


def get_tx(db: Db, tx_id: int) -> Tx | None:
    rows = db.query("SELECT * FROM transactions WHERE id = ?", (tx_id,))
    return _tx(rows[0]) if rows else None


def save_tx(db: Db, t: Tx) -> int:
    with db.write() as c:
        if t.id is None:
            cur = c.execute(f"INSERT INTO transactions ({_TX_COLS}) VALUES ({_TX_MARKS})", _tx_values(t))
            return int(cur.lastrowid or 0)
        sets = ", ".join(f"{col.strip()}=?" for col in _TX_COLS.split(","))
        c.execute(f"UPDATE transactions SET {sets} WHERE id=?", (*_tx_values(t), t.id))
        return t.id


def delete_tx(db: Db, tx_id: int) -> None:
    with db.write() as c:
        c.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))


def set_tx_amounts(db: Db, rows: list[tuple[int, Decimal]]) -> None:
    """(id, amount) pairs: derived amounts of 期初餘額 rows."""
    with db.write() as c:
        c.executemany("UPDATE transactions SET amount = ? WHERE id = ?", [(str(a), i) for i, a in rows])


def set_tx_balance(db: Db, tx_id: int, balance: Decimal) -> None:
    with db.write() as c:
        c.execute("UPDATE transactions SET balance = ? WHERE id = ?", (str(balance), tx_id))


def txs_in_group(db: Db, group: str) -> list[Tx]:
    return [_tx(r) for r in db.query("SELECT * FROM transactions WHERE transfer_group = ? ORDER BY id", (group,))]


def replace_txs(db: Db, remove_ids: list[int], add: list[Tx]) -> list[int]:
    """Delete and insert in one transaction (edits of two-legged transfers)."""
    ids = []
    with db.write() as c:
        for i in remove_ids:
            c.execute("DELETE FROM transactions WHERE id = ?", (i,))
        for t in add:
            cur = c.execute(f"INSERT INTO transactions ({_TX_COLS}) VALUES ({_TX_MARKS})", _tx_values(t))
            ids.append(int(cur.lastrowid or 0))
    return ids


# ── recurring ────────────────────────────────────────────────────────────

_REC_COLS = ("line", "freq", "start_date", "end_date", "last_date", "active", "error", "sort")


def _recurring(r: sqlite3.Row) -> Recurring:
    return Recurring(
        r["id"], r["line"], r["freq"], r["start_date"], r["end_date"], r["last_date"], bool(r["active"]), r["error"], r["sort"]
    )


def list_recurring(db: Db) -> list[Recurring]:
    return [_recurring(r) for r in db.query("SELECT * FROM recurring ORDER BY sort, id")]


def get_recurring(db: Db, rule_id: int) -> Recurring | None:
    rows = db.query("SELECT * FROM recurring WHERE id = ?", (rule_id,))
    return _recurring(rows[0]) if rows else None


def save_recurring(db: Db, r: Recurring) -> int:
    values = (r.line, r.freq, r.start_date, r.end_date, r.last_date, int(r.active), r.error, r.sort)
    with db.write() as c:
        if r.id is None:
            cur = c.execute(
                f"INSERT INTO recurring ({', '.join(_REC_COLS)}) VALUES ({', '.join('?' * len(_REC_COLS))})", values
            )
            return int(cur.lastrowid or 0)
        c.execute(f"UPDATE recurring SET {', '.join(f'{k}=?' for k in _REC_COLS)} WHERE id=?", (*values, r.id))
        return r.id


def has_recurring_tx(db: Db, rule_id: int, start: str, end: str) -> bool:
    """Whether the rule already posted in [start, end) (a 定額 trades on the first trading day from start)."""
    rows = db.query("SELECT 1 FROM transactions WHERE recurring_id = ? AND date >= ? AND date < ? LIMIT 1", (rule_id, start, end))
    return bool(rows)


def mark_recurring(db: Db, tx_id: int, rule_id: int) -> None:
    """Tag a transaction (and the other rows of its group) as posted by a rule."""
    with db.write() as c:
        c.execute(
            "UPDATE transactions SET recurring_id = ? WHERE id = ?"
            " OR transfer_group = (SELECT transfer_group FROM transactions WHERE id = ?)",
            (rule_id, tx_id, tx_id),
        )


def delete_recurring(db: Db, rule_id: int) -> None:
    """The rule only; transactions it posted stay (and forget where they came from)."""
    with db.write() as c:
        c.execute("UPDATE transactions SET recurring_id = NULL WHERE recurring_id = ?", (rule_id,))
        c.execute("DELETE FROM recurring WHERE id = ?", (rule_id,))


# ── categories ───────────────────────────────────────────────────


def _category(r: sqlite3.Row) -> Category:
    return Category(r["id"], r["name"], r["kind"], _d(r["budget"]), r["sort"], bool(r["archived"]), r["parent_id"], r["color"])


def list_categories(db: Db, kind: str | None = None) -> list[Category]:
    if kind:
        rows = db.query("SELECT * FROM categories WHERE kind = ? ORDER BY sort, id", (kind,))
    else:
        rows = db.query("SELECT * FROM categories ORDER BY kind, sort, id")
    return [_category(r) for r in rows]


def get_category(db: Db, category_id: int) -> Category | None:
    rows = db.query("SELECT * FROM categories WHERE id = ?", (category_id,))
    return _category(rows[0]) if rows else None


def add_category(db: Db, name: str, kind: str) -> int:
    with db.write() as c:
        sort = c.execute("SELECT coalesce(max(sort), 0) FROM categories WHERE kind = ? AND sort < 99", (kind,)).fetchone()[0]
        cur = c.execute("INSERT INTO categories (name, kind, sort) VALUES (?, ?, ?)", (name, kind, sort + 1))
        return int(cur.lastrowid or 0)


def set_category_budget(db: Db, category_id: int, budget: Decimal | None) -> None:
    with db.write() as c:
        c.execute("UPDATE categories SET budget = ? WHERE id = ?", (_s(budget), category_id))


def rename_category(db: Db, category_id: int, name: str, recurring: Iterable[Recurring] = ()) -> None:
    """Renames a category and saves the recurring rules rewritten to use the new name, together."""
    with db.write() as c:
        c.execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))
        for r in recurring:
            c.execute("UPDATE recurring SET line = ? WHERE id = ?", (r.line, r.id))


def set_category_parent(db: Db, category_id: int, parent_id: int | None) -> None:
    with db.write() as c:
        c.execute("UPDATE categories SET parent_id = ? WHERE id = ?", (parent_id, category_id))


def set_category_color(db: Db, category_id: int, color: str | None) -> None:
    with db.write() as c:
        c.execute("UPDATE categories SET color = ? WHERE id = ?", (color, category_id))


def set_category_archived(db: Db, category_id: int, archived: bool) -> None:
    with db.write() as c:
        c.execute("UPDATE categories SET archived = ? WHERE id = ?", (int(archived), category_id))


def set_category_sorts(db: Db, sorts: Iterable[tuple[int, int]]) -> None:
    """(category id, sort) pairs, saved together."""
    with db.write() as c:
        c.executemany("UPDATE categories SET sort = ? WHERE id = ?", [(s, i) for i, s in sorts])


def delete_category(db: Db, category_id: int) -> None:
    with db.write() as c:
        c.execute("DELETE FROM categories WHERE id = ?", (category_id,))


def category_use_counts(db: Db) -> dict[int, int]:
    rows = db.query("SELECT category_id, count(*) AS n FROM transactions WHERE category_id IS NOT NULL GROUP BY category_id")
    return {r["category_id"]: r["n"] for r in rows}


_PLAN_COLS = (
    "kind", "name", "target_month", "price", "down_ratio", "one_off", "loan_rate", "loan_years",
    "grace_years", "monthly_cost", "rent_saved", "account_ids", "active", "sort", "scope",
)


def _life_plan(r: sqlite3.Row) -> LifePlan:
    ids = [int(x) for x in r["account_ids"].split(",") if x]
    return LifePlan(
        r["id"], r["kind"], r["name"], Decimal(r["price"]), r["target_month"], _d(r["down_ratio"]),
        _d(r["one_off"]), _d(r["loan_rate"]), _d(r["loan_years"]), _d(r["grace_years"]),
        _d(r["monthly_cost"]), _d(r["rent_saved"]), ids, bool(r["active"]), r["sort"], r["scope"],
    )


def list_life_plans(db: Db) -> list[LifePlan]:
    return [_life_plan(r) for r in db.query("SELECT * FROM life_plans ORDER BY coalesce(target_month, '9999'), sort, id")]


def save_life_plan(db: Db, p: LifePlan) -> int:
    values = (
        p.kind, p.name, p.target_month, str(p.price), _s(p.down_ratio), _s(p.one_off), _s(p.loan_rate),
        _s(p.loan_years), _s(p.grace_years), _s(p.monthly_cost), _s(p.rent_saved),
        ",".join(str(i) for i in p.account_ids or []), int(p.active), p.sort, p.scope,
    )
    with db.write() as c:
        if p.id is None:
            cur = c.execute(
                f"INSERT INTO life_plans ({', '.join(_PLAN_COLS)}) VALUES ({', '.join('?' * len(_PLAN_COLS))})", values
            )
            return int(cur.lastrowid or 0)
        c.execute(f"UPDATE life_plans SET {', '.join(f'{k}=?' for k in _PLAN_COLS)} WHERE id=?", (*values, p.id))
        return p.id


def delete_life_plan(db: Db, plan_id: int) -> None:
    with db.write() as c:
        c.execute("DELETE FROM life_plans WHERE id = ?", (plan_id,))


# ── prices & fx ──────────────────────────────────────────────────────────


def put_prices(db: Db, rows: Iterable[tuple[str, str, Decimal]]) -> None:
    """rows: (symbol, date, close)."""
    with db.write() as c:
        c.executemany(
            "INSERT OR REPLACE INTO prices (symbol, date, close) VALUES (?, ?, ?)",
            [(s, d, str(p)) for s, d, p in rows],
        )


def closes_from(db: Db, symbol: str, start: str) -> list[tuple[str, Decimal]]:
    """Stored daily closes on or after `start`, oldest first."""
    rows = db.query("SELECT date, close FROM prices WHERE symbol = ? AND date >= ? ORDER BY date", (symbol, start))
    return [(r["date"], Decimal(r["close"])) for r in rows]


def put_fx(db: Db, rows: Iterable[tuple[str, str, Decimal]]) -> None:
    """Market mid-rates. rows: (currency, date, rate in TWD). Never overwrites a bank board row."""
    with db.write() as c:
        c.executemany(
            "INSERT INTO fx_rates (currency, date, rate, source) VALUES (?, ?, ?, 'yahoo')"
            " ON CONFLICT(currency, date) DO UPDATE SET rate = excluded.rate WHERE source = 'yahoo'",
            [(cur, d, str(r)) for cur, d, r in rows],
        )


def put_board_fx(db: Db, source: str, rows: Iterable[tuple[str, str, Decimal, Decimal]]) -> None:
    """Bank board rates. rows: (currency, date, bank buys, bank sells)."""
    with db.write() as c:
        c.executemany(
            "INSERT OR REPLACE INTO fx_rates (currency, date, rate, sell, source) VALUES (?, ?, ?, ?, ?)",
            [(cur, d, str(buy), str(sell), source) for cur, d, buy, sell in rows],
        )


def fx_on(db: Db, currency: str, date: str | None = None, prefer: str | None = None) -> tuple[Decimal, str] | None:
    """The rate on `date` or the closest earlier day; without a date (or nothing earlier), the newest.

    With `prefer` (a source such as 'cathay') and no date, the newest row from that source wins when
    there is one, so valuation follows the bank board even if a later market rate exists.
    """
    if currency == "TWD":
        return Decimal(1), date or ""
    if date:
        rows = db.query(
            "SELECT rate, date FROM fx_rates WHERE currency = ? AND date <= ? ORDER BY date DESC LIMIT 1",
            (currency, date),
        )
        if rows:
            return Decimal(rows[0]["rate"]), rows[0]["date"]
    if prefer:
        rows = db.query(
            "SELECT rate, date FROM fx_rates WHERE currency = ? AND source = ? ORDER BY date DESC LIMIT 1",
            (currency, prefer),
        )
        if rows:
            return Decimal(rows[0]["rate"]), rows[0]["date"]
    rows = db.query("SELECT rate, date FROM fx_rates WHERE currency = ? ORDER BY date DESC LIMIT 1", (currency,))
    return (Decimal(rows[0]["rate"]), rows[0]["date"]) if rows else None


def fx_last_two(db: Db, currency: str) -> list[tuple[str, Decimal]]:
    """The two newest market mid-rates, newest first. Bank board rows are left out: a board rate
    next to a market one would read as a move."""
    rows = db.query(
        "SELECT date, rate FROM fx_rates WHERE currency = ? AND source = 'yahoo' ORDER BY date DESC LIMIT 2", (currency,)
    )
    return [(r["date"], Decimal(r["rate"])) for r in rows]


def fx_sell_on(db: Db, currency: str, date: str) -> Decimal | None:
    """The bank's selling rate on `date` or the closest earlier board day (None without board data)."""
    rows = db.query(
        "SELECT sell FROM fx_rates WHERE currency = ? AND date <= ? AND sell IS NOT NULL ORDER BY date DESC LIMIT 1",
        (currency, date),
    )
    return Decimal(rows[0]["sell"]) if rows else None


# ── 除權息 ───────────────────────────────────────────────────────────────


def put_dividend_events(db: Db, rows: Iterable[tuple[str, str, Decimal | None, str | None]]) -> None:
    """rows: (symbol, ex date, cash per share or None, pay date or None). A later feed without the
    amount never erases one already known."""
    with db.write() as c:
        c.executemany(
            "INSERT INTO dividend_events (symbol, ex_date, cash, pay_date) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(symbol, ex_date) DO UPDATE SET cash = COALESCE(excluded.cash, cash),"
            " pay_date = COALESCE(excluded.pay_date, pay_date)",
            [(s, d, _s(cash), pay) for s, d, cash, pay in rows],
        )


def dividend_events(db: Db, symbols: Iterable[str], start: str, end: str) -> list[tuple[str, str, Decimal | None, str | None]]:
    """(symbol, ex date, cash per share, pay date) with start <= ex date <= end, earliest first."""
    symbols = list(symbols)
    if not symbols:
        return []
    marks = ",".join("?" * len(symbols))
    rows = db.query(
        f"SELECT * FROM dividend_events WHERE symbol IN ({marks}) AND ex_date BETWEEN ? AND ? ORDER BY ex_date, symbol",
        (*symbols, start, end),
    )
    return [(r["symbol"], r["ex_date"], _d(r["cash"]), r["pay_date"]) for r in rows]


# ── 自選股、投資筆記、提醒 ─────────────────────────────────────────────────


def list_watchlist(db: Db) -> list[str]:
    return [r["symbol"] for r in db.query("SELECT symbol FROM watchlist ORDER BY sort, added_at, symbol")]


def add_watch(db: Db, symbol: str, added_at: str) -> None:
    with db.write() as c:
        nxt = c.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM watchlist").fetchone()[0]
        c.execute("INSERT OR IGNORE INTO watchlist (symbol, added_at, sort) VALUES (?, ?, ?)", (symbol, added_at, nxt))


def remove_watch(db: Db, symbol: str) -> None:
    with db.write() as c:
        c.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))


def _note(r: sqlite3.Row) -> Note:
    return Note(
        r["symbol"], r["thesis"], r["red_lines"], _d(r["band_low"]), _d(r["band_high"]), r["review_months"],
        r["last_review"], r["created_at"], r["updated_at"],
    )  # fmt: skip


def get_note(db: Db, symbol: str) -> Note | None:
    rows = db.query("SELECT * FROM notes WHERE symbol = ?", (symbol,))
    return _note(rows[0]) if rows else None


def list_notes(db: Db) -> dict[str, Note]:
    return {r["symbol"]: _note(r) for r in db.query("SELECT * FROM notes")}


def save_note(db: Db, n: Note) -> None:
    with db.write() as c:
        c.execute(
            "INSERT INTO notes (symbol, thesis, red_lines, band_low, band_high, review_months, last_review, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET thesis = excluded.thesis,"
            " red_lines = excluded.red_lines, band_low = excluded.band_low, band_high = excluded.band_high,"
            " review_months = excluded.review_months, last_review = excluded.last_review, updated_at = excluded.updated_at",
            (n.symbol, n.thesis, n.red_lines, _s(n.band_low), _s(n.band_high), n.review_months, n.last_review,
             n.created_at, n.updated_at),
        )  # fmt: skip


def delete_note(db: Db, symbol: str) -> None:
    with db.write() as c:
        c.execute("DELETE FROM notes WHERE symbol = ?", (symbol,))


def seen_alerts(db: Db) -> set[str]:
    return {r["key"] for r in db.query("SELECT key FROM alert_seen")}


def notified_alerts(db: Db) -> set[str]:
    return {r["key"] for r in db.query("SELECT key FROM alert_notified")}


def mark_alerts_notified(db: Db, keys: Iterable[str], date: str) -> None:
    with db.write() as c:
        c.executemany("INSERT OR REPLACE INTO alert_notified (key, date) VALUES (?, ?)", [(k, date) for k in keys])


def mark_alert_seen(db: Db, key: str, date: str) -> None:
    with db.write() as c:
        c.execute("INSERT OR REPLACE INTO alert_seen (key, date) VALUES (?, ?)", (key, date))
        c.execute("DELETE FROM alert_seen WHERE date < date(?, '-60 days')", (date,))  # keys carry a date; old ones never recur


# ── 財報快照 ──────────────────────────────────────────────────────────────


def put_fundamentals(db: Db, symbol: str, annual: dict[str, dict[str, Decimal]], currency: str | None, source: str, fetched_at: str) -> None:
    with db.write() as c:
        c.execute("DELETE FROM fundamentals WHERE symbol = ?", (symbol,))
        c.executemany(
            "INSERT INTO fundamentals (symbol, period, field, value, currency) VALUES (?, ?, ?, ?, ?)",
            [(symbol, y, f, str(v), currency) for y, row in annual.items() for f, v in row.items()],
        )
        c.execute("INSERT OR REPLACE INTO fund_meta (symbol, fetched_at, source, error) VALUES (?, ?, ?, NULL)", (symbol, fetched_at, source))


def fundamentals_error(db: Db, symbol: str, error: str, fetched_at: str, source: str) -> None:
    """Keep whatever was stored; remember the failure (and when) so it isn't retried on every open."""
    with db.write() as c:
        c.execute(
            "INSERT INTO fund_meta (symbol, fetched_at, source, error) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(symbol) DO UPDATE SET error = excluded.error, fetched_at = excluded.fetched_at",
            (symbol, fetched_at, source, error),
        )


def get_fundamentals(db: Db, symbol: str) -> tuple[dict[str, dict[str, Decimal]], str | None, dict[str, Any] | None]:
    """(annual figures, currency, meta {fetched_at, source, error})."""
    annual: dict[str, dict[str, Decimal]] = {}
    currency = None
    for r in db.query("SELECT * FROM fundamentals WHERE symbol = ?", (symbol,)):
        annual.setdefault(r["period"], {})[r["field"]] = Decimal(r["value"])
        currency = r["currency"] or currency
    rows = db.query("SELECT fetched_at, source, error FROM fund_meta WHERE symbol = ?", (symbol,))
    meta = dict(rows[0]) if rows else None
    return annual, currency, meta


# ── snapshots & settings ─────────────────────────────────────────────────


def put_snapshot(db: Db, date: str, total: Decimal, breakdown: dict) -> None:
    with db.write() as c:
        c.execute(
            "INSERT OR REPLACE INTO snapshots (date, total_twd, breakdown_json) VALUES (?, ?, ?)",
            (date, str(total), json.dumps(breakdown, ensure_ascii=False)),
        )


def list_snapshots(db: Db) -> list[tuple[str, Decimal]]:
    return [(r["date"], Decimal(r["total_twd"])) for r in db.query("SELECT date, total_twd FROM snapshots ORDER BY date")]


def list_snapshot_breakdowns(db: Db) -> list[tuple[str, Decimal, dict[str, Any]]]:
    rows = db.query("SELECT date, total_twd, breakdown_json FROM snapshots ORDER BY date")
    return [(r["date"], Decimal(r["total_twd"]), json.loads(r["breakdown_json"])) for r in rows]


def get_setting(db: Db, key: str, default: str) -> str:
    rows = db.query("SELECT value FROM settings WHERE key = ?", (key,))
    return rows[0]["value"] if rows else default


def set_setting(db: Db, key: str, value: str) -> None:
    with db.write() as c:
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
