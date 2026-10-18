-- 子類別 (2026-10-18): one level only, e.g. 數碼、運動 under 消費. See DESIGN.md「子類別」.
ALTER TABLE categories ADD COLUMN parent_id INTEGER REFERENCES categories(id);
