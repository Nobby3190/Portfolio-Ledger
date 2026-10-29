-- 分類顏色 (2026-10-29): a tone name (sky, plum…), each theme has its own value; NULL = from the name.
-- See DESIGN.md「管理分類：顏色、新增、封存、排序」.
ALTER TABLE categories ADD COLUMN color TEXT;
