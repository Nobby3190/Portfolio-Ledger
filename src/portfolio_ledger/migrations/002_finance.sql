-- Bookkeeping categories with an optional monthly budget, time deposits, savings goals.

CREATE TABLE categories (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    kind     TEXT NOT NULL,                  -- income / expense
    budget   TEXT,                           -- monthly budget (TWD), expense only
    sort     INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    UNIQUE (name, kind)
);

INSERT INTO categories (name, kind, sort) VALUES
    ('餐飲', 'expense', 1), ('交通', 'expense', 2), ('居住', 'expense', 3), ('購物', 'expense', 4),
    ('娛樂', 'expense', 5), ('醫療', 'expense', 6), ('保險', 'expense', 7), ('教育', 'expense', 8),
    ('其他', 'expense', 99),
    ('薪資', 'income', 1), ('獎金', 'income', 2), ('利息', 'income', 3), ('其他收入', 'income', 99);

-- Time deposits are accounts of type 'deposit' with these terms.
ALTER TABLE accounts ADD COLUMN rate TEXT;           -- annual interest, percent
ALTER TABLE accounts ADD COLUMN start_date TEXT;
ALTER TABLE accounts ADD COLUMN maturity_date TEXT;

CREATE TABLE goals (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    target      TEXT NOT NULL,                -- TWD
    deadline    TEXT,                         -- YYYY-MM-DD
    account_ids TEXT NOT NULL DEFAULT '',     -- comma-separated; empty = whole net worth
    sort        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX transactions_group ON transactions(transfer_group);
