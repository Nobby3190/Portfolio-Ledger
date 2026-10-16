-- v1.4 (2026-10-15): 股利、自選股、投資筆記、價格提醒、財報快照. See DESIGN.md「v1.4」.

-- 除權息: upcoming (TWSE TWT48U) and past (FinMind) cash dividends per share.
CREATE TABLE dividend_events (
    symbol   TEXT NOT NULL,
    ex_date  TEXT NOT NULL,
    cash     TEXT,           -- per share, the security's currency; NULL = not announced yet
    pay_date TEXT,
    PRIMARY KEY (symbol, ex_date)
);

-- 自選股: stocks the user is thinking of buying.
CREATE TABLE watchlist (
    symbol   TEXT PRIMARY KEY,
    added_at TEXT NOT NULL,
    sort     INTEGER NOT NULL DEFAULT 0
);

-- 投資筆記: one per symbol, shared by holdings and the watchlist; kept after selling out.
CREATE TABLE notes (
    symbol        TEXT PRIMARY KEY,
    thesis        TEXT NOT NULL DEFAULT '',
    red_lines     TEXT NOT NULL DEFAULT '',
    band_low      TEXT,          -- 合理價區間, the security's currency
    band_high     TEXT,
    review_months INTEGER,       -- NULL = no review reminder
    last_review   TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Reminders the user dismissed (「知道了」); key like 'day:2330:2026-10-15'.
CREATE TABLE alert_seen (
    key  TEXT PRIMARY KEY,
    date TEXT NOT NULL
);

-- 財報快照: raw annual figures, refetched after 7 days.
CREATE TABLE fundamentals (
    symbol   TEXT NOT NULL,
    period   TEXT NOT NULL,      -- fiscal year, '2025'
    field    TEXT NOT NULL,
    value    TEXT NOT NULL,
    currency TEXT,
    PRIMARY KEY (symbol, period, field)
);

CREATE TABLE fund_meta (
    symbol     TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    source     TEXT NOT NULL,
    error      TEXT
);

-- 台股 本益比、殖利率、股價淨值比 (TWSE BWIBBU_ALL).
ALTER TABLE securities ADD COLUMN pe TEXT;
ALTER TABLE securities ADD COLUMN pb TEXT;
ALTER TABLE securities ADD COLUMN dividend_yield TEXT;
