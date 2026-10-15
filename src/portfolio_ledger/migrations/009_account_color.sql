-- 帳戶顏色 (2026-10-14): '#rrggbb' picked by hand; NULL = chosen from the bank/broker in the name.
ALTER TABLE accounts ADD COLUMN color TEXT;
