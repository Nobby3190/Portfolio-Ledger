-- 期初餘額: a deposit that states the account's balance on its date; its amount is derived
-- (balance − everything dated earlier on the account), so backfilled entries don't count twice.
-- Existing first deposits are converted once by Ledger (in Decimal), see Ledger._convert_openings.
ALTER TABLE transactions ADD COLUMN balance TEXT;
