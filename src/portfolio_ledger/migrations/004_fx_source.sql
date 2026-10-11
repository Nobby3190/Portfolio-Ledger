-- Bank board rates (國泰世華): rate = bank buys (valuation), sell = bank sells (cost of buying
-- foreign currency). source tells market mid-rates (yahoo) and bank board rows (cathay) apart.
ALTER TABLE fx_rates ADD COLUMN sell TEXT;
ALTER TABLE fx_rates ADD COLUMN source TEXT NOT NULL DEFAULT 'yahoo';
