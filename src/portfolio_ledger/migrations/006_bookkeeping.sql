-- 記帳強化 (v1.3): recurring income/expense, loan accounts.

-- Recurring entries: a one-line command (no date) posted on each due date up to today.
CREATE TABLE recurring (
    id         INTEGER PRIMARY KEY,
    line       TEXT NOT NULL,                -- e.g. 支出 15000 居住 @台新 # 房租
    freq       TEXT NOT NULL,                -- monthly / weekly / yearly
    start_date TEXT NOT NULL,                -- anchors the day: day of month / weekday / month-day
    end_date   TEXT,
    last_date  TEXT,                         -- last date posted; NULL = nothing posted yet
    active     INTEGER NOT NULL DEFAULT 1,
    error      TEXT,                         -- why the last posting failed
    sort       INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE transactions ADD COLUMN recurring_id INTEGER;

-- Loans are accounts of type 'loan'; rate and start_date (drawdown) are shared with time deposits.
ALTER TABLE accounts ADD COLUMN principal TEXT;
ALTER TABLE accounts ADD COLUMN term_years TEXT;
ALTER TABLE accounts ADD COLUMN grace_years TEXT;

INSERT OR IGNORE INTO categories (name, kind, sort) VALUES ('貸款利息', 'expense', 9);
