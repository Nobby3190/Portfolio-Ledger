-- Money and quantities are TEXT holding Decimal strings: never REAL.

CREATE TABLE accounts (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    type         TEXT NOT NULL,              -- broker_tw / broker_us / bank / cash
    currency     TEXT NOT NULL,              -- TWD / USD / ...
    fee_discount TEXT,                       -- NULL: use the global setting
    fee_min      TEXT,
    archived     INTEGER NOT NULL DEFAULT 0,
    sort         INTEGER NOT NULL DEFAULT 0
);

-- Every listed security we know of. last_* is the newest close, refreshed for the whole
-- TW market at once; history for held symbols lives in prices.
CREATE TABLE securities (
    symbol     TEXT PRIMARY KEY,             -- as the user types it: 2330, 00679B, VOO
    name       TEXT NOT NULL,
    market     TEXT NOT NULL,                -- TWSE / TPEX / US
    currency   TEXT NOT NULL,
    kind       TEXT NOT NULL,                -- stock / etf / bond_etf
    last_close TEXT,
    prev_close TEXT,
    last_date  TEXT
);

CREATE TABLE transactions (
    id             INTEGER PRIMARY KEY,
    account_id     INTEGER NOT NULL REFERENCES accounts(id),
    date           TEXT NOT NULL,            -- YYYY-MM-DD
    kind           TEXT NOT NULL,            -- buy/sell/cash_dividend/stock_dividend/split/deposit/withdraw
    symbol         TEXT REFERENCES securities(symbol),
    qty            TEXT,                     -- split: the ratio (10 = 1→10)
    price          TEXT,
    amount         TEXT NOT NULL,            -- effect on the account's cash, signed, account currency
    fee            TEXT NOT NULL DEFAULT '0',
    tax            TEXT NOT NULL DEFAULT '0',
    fx_rate        TEXT,                     -- account currency → TWD on that day; NULL for TWD
    category_id    INTEGER,                  -- bookkeeping (v1.1)
    transfer_group TEXT,                     -- pairs both legs of a transfer (v1.1)
    note           TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX transactions_date ON transactions(date, id);
CREATE INDEX transactions_symbol ON transactions(symbol);

CREATE TABLE prices (
    symbol TEXT NOT NULL,
    date   TEXT NOT NULL,
    close  TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE fx_rates (
    currency TEXT NOT NULL,                  -- 1 unit of this currency in TWD
    date     TEXT NOT NULL,
    rate     TEXT NOT NULL,
    PRIMARY KEY (currency, date)
);

CREATE TABLE snapshots (
    date           TEXT PRIMARY KEY,
    total_twd      TEXT NOT NULL,
    breakdown_json TEXT NOT NULL
);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
