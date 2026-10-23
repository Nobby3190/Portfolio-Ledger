-- 信用卡自動扣繳 (2026-10-23): a card's statement day and payment day (day of month, 1–31).
-- The autopay itself is a monthly recurring rule `還 @卡 @銀行`; see DESIGN.md「信用卡自動扣繳」.
ALTER TABLE accounts ADD COLUMN statement_day INTEGER;
ALTER TABLE accounts ADD COLUMN pay_day INTEGER;
