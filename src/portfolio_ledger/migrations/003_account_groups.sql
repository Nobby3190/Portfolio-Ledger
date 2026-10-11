-- A multi-currency account (e.g. a bank's 外幣綜合存款) is a group of one-currency accounts named
-- "{group}-{CUR}" that share group_name. Money logic stays per currency; only the UI groups them.
ALTER TABLE accounts ADD COLUMN group_name TEXT;
CREATE INDEX accounts_group ON accounts(group_name);
