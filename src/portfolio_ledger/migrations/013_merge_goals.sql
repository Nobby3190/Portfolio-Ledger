-- 目標與計劃 (2026-10-23): savings goals become life plans, one list on the 規劃 page.
-- scope is the old goal 追蹤範圍; plans with ticked accounts were already "accounts", the rest share the net worth.
-- Moved goals stay out of the projection and the health check (active = 0), so no number changes there.
ALTER TABLE life_plans ADD COLUMN scope TEXT NOT NULL DEFAULT 'total';
UPDATE life_plans SET scope = 'accounts' WHERE account_ids != '';
INSERT INTO life_plans (kind, name, price, target_month, scope, account_ids, active, sort)
    SELECT 'other', name, target, substr(deadline, 1, 7), scope, account_ids, 0, sort FROM goals;
DROP TABLE goals;
