-- 人生計劃 (v1.2): big purchases (house, car, other) that feed the FIRE projection.
-- Every number is optional except price; amounts are TWD in today's money, rates are percent.

CREATE TABLE life_plans (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,               -- house / car / other
    name         TEXT NOT NULL,
    target_month TEXT,                        -- YYYY-MM
    price        TEXT NOT NULL,
    down_ratio   TEXT,                        -- %, empty = paid in full
    one_off      TEXT,                        -- taxes, fees, renovation...
    loan_rate    TEXT,                        -- annual %
    loan_years   TEXT,
    grace_years  TEXT,
    monthly_cost TEXT,                        -- running cost after the purchase
    rent_saved   TEXT,                        -- rent no longer paid after the purchase
    account_ids  TEXT NOT NULL DEFAULT '',    -- where the down payment is saved; empty = net worth
    active       INTEGER NOT NULL DEFAULT 1,  -- included in the projection and health check
    sort         INTEGER NOT NULL DEFAULT 0
);
