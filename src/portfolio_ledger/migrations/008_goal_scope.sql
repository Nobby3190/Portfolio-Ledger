-- 儲蓄目標的追蹤範圍 (2026-10-13): cash / cash_deposit / total / accounts.
-- Existing goals keep their numbers: ticked accounts → accounts, none ticked → the whole net worth.
ALTER TABLE goals ADD COLUMN scope TEXT NOT NULL DEFAULT 'total';
UPDATE goals SET scope = 'accounts' WHERE account_ids != '';
