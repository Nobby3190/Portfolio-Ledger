// Mirrors the dicts built in src/portfolio_ledger/services/ledger.py. Every money value is a
// display-ready string from Python; the page never does arithmetic on money.

export type Sign = -1 | 0 | 1;

export interface Holding {
  symbol: string;
  name: string;
  currency: string;
  qty: string;
  avg_cost: string;
  cost_currency: string;
  close: string | null;
  close_date: string | null;
  value: string;
  value_twd: string;
  unrealized: string;
  unrealized_pct: string | null;
  realized: string | null;
  dividends: string | null;
  day_change: string;
  day_pct: string | null;
  sign: Sign;
  day_sign: Sign;
  weight: number;
  accounts: string[];
  tx_ids: number[];
}

export interface Closed {
  symbol: string;
  name: string;
  realized: string;
  dividends: string | null;
  sign: Sign;
  tx_ids: number[];
}

export interface TxRow {
  id: number;
  date: string;
  kind: string;
  label: string;
  symbol: string | null;
  name: string | null;
  qty: string | null;
  ratio: string | null;
  price: string | null;
  amount: string | null;
  sign: Sign;
  currency: string;
  account: string;
  note: string;
  category: string | null;
  to_account: string | null;
  received: string | null;
  twd: string | null;
  value: number; // TWD, unsigned: amount filters and totals in the search panel
  recurring: boolean; // posted by a 週期性 rule
}

export interface AccountRow {
  id: number;
  name: string;
  type: string;
  type_label: string;
  currency: string;
  cash: string;
  cash_sign: Sign;
  holdings: string | null;
  fee_discount: string | null;
  fee_min: string | null;
  group_name: string | null;
  value_twd: string;
  rate: string | null;
  start_date: string | null;
  maturity_date: string | null;
  principal: string | null; // loans
  term_years: string | null;
  grace_years: string | null;
  archived: boolean;
}

export interface Loan {
  id: number;
  name: string;
  currency: string;
  owed: string;
  principal: string | null;
  ratio: number | null; // share repaid
  rate: string | null;
  payment: string | null; // this month's scheduled payment
  payoff: string | null; // YYYY-MM at the scheduled payment
  months_left: number | null;
  interest_left: string | null;
  done: boolean;
}

export interface Deposit {
  id: number;
  name: string;
  currency: string;
  principal: string;
  rate: string | null;
  start_date: string | null;
  maturity_date: string | null;
  days_left: number | null;
  matured: boolean;
  soon: boolean;
  accrued: string | null;
}

export interface FxPosition {
  currency: string;
  name: string;
  balance: string;
  avg_rate: string | null;
  rate: string | null;
  value_twd: string | null;
  gain: string | null;
  sign: Sign;
}

export interface Settings {
  fee_discount: string;
  fee_min: string;
  privacy: '0' | '1';
  up_color: 'red' | 'green';
  fx_source: 'cathay' | 'market';
}

export interface State {
  total: string;
  day_change: string;
  day_change_pct: string | null;
  day_sign: Sign;
  total_return: string;
  total_return_pct: string | null;
  return_sign: Sign;
  allocation: { label: string; value: string; ratio: number }[];
  allocation_groups: {
    groups: { key: 'invest' | 'cash'; label: string; value: string; ratio: number; items: { label: string; value: string; ratio: number }[] }[];
    debts: { label: string; value: string }[];
    debt_total: string | null;
  };
  history: { date: string; total: string }[];
  holdings: Holding[];
  holdings_value: string;
  holdings_unrealized: string;
  holdings_unrealized_sign: Sign;
  closed: Closed[];
  transactions: TxRow[];
  categories: { id: number; name: string; kind: 'income' | 'expense'; uses: number }[];
  deposits: Deposit[];
  loans: Loan[];
  fx_positions: FxPosition[];
  accounts: AccountRow[];
  account_groups: AccountGroup[];
  account_types: Record<string, string>;
  currencies: Record<string, string>;
  settings: Settings;
  missing_fx: string[];
  quotes: {
    latest: string | null;
    oldest: string | null;
    refreshed_at: string | null;
    running: boolean;
    errors: string[];
    tw_listed: number;
  };
  today: string;
}

export type Preview =
  | { status: 'empty' }
  | { status: 'error'; message: string }
  | { status: 'incomplete'; title: string | null; message: string }
  | {
      status: 'ready';
      title: string;
      parts: string[];
      total: string | null;
      currency: string;
      sign: Sign;
      guessed_category?: string | null; // 自動分類: taken from past entries with the same note
    }
  | {
      status: 'lookup';
      results: {
        symbol: string;
        name: string;
        close: string | null;
        change: string | null;
        sign: Sign;
        date: string | null;
        held: string | null;
      }[];
    };

export interface AccountInput {
  id?: number;
  name: string;
  type: string;
  currency?: string;
  fee_discount?: string;
  fee_min?: string;
  rate?: string;
  start_date?: string;
  maturity_date?: string;
  principal?: string;
  term_years?: string;
  grace_years?: string;
  archived?: boolean;
}

export interface MonthReport {
  month: string;
  label: string;
  prev: string;
  next: string | null;
  is_current: boolean;
  income: string;
  expense: string;
  net: string;
  net_sign: Sign;
  savings_rate: string | null;
  budget: string | null;
  budget_total_setting: string;
  budget_ratio: number | null;
  budget_left: string | null;
  over: boolean;
  days_left: number | null;
  per_day: string | null;
  categories: {
    id: number;
    name: string;
    spent: string;
    budget: string | null;
    budget_raw: string;
    budget_ratio: number | null;
    share: number;
    last: string | null;
    delta: string | null;
    delta_sign: Sign;
  }[];
  income_categories: { name: string; amount: string }[];
  trend: MonthPoint[]; // 6 months ending at this month at the latest (the chart)
  tabs: MonthPoint[]; // the trend, plus the months still to come this year when it ends at this month
  is_future: boolean;
  has_data: boolean;
}

export interface YearChange {
  delta: string;
  pct: string | null;
  sign: Sign;
}

export interface YearReport {
  year: number;
  label: string;
  is_current: boolean;
  elapsed: number; // months the averages are over
  income: string;
  expense: string;
  net: string;
  net_sign: Sign;
  savings_rate: string | null;
  per_month: string;
  compare_label: string; // 比 2025 年, or 比 2025 年 1–10 月 for the year in progress
  vs_last: {
    income: YearChange | null;
    expense: YearChange | null;
    net: YearChange | null;
    savings_rate: string | null; // last year's
  };
  categories: {
    id: number;
    name: string;
    amount: string;
    share: number;
    per_month: string;
    last: string | null;
    delta: string | null;
    delta_sign: Sign;
    budget: string | null;
    budget_ratio: number | null;
  }[];
  income_categories: { name: string; amount: string; share: number }[];
  trend: MonthPoint[];
  worth: { start: string; end: string; change: string; pct: string | null; sign: Sign } | null;
  tabs: { year: number; label: string; expense: string }[];
  has_data: boolean;
}

export interface RecurringRule {
  id: number;
  line: string;
  title: string;
  kind: string;
  category: string | null;
  amount: string | null;
  monthly: number | null; // this rule per month (weekly ×52÷12, yearly ÷12); null when paused or no amount
  freq: RecurringFreq;
  freq_label: string;
  start_date: string;
  end_date: string | null;
  last_date: string | null;
  next_date: string | null;
  active: boolean;
  error: string | null;
}

export type RecurringFreq = 'monthly' | 'weekly' | 'yearly';

export interface RecurringInput {
  id?: number;
  line: string;
  freq: RecurringFreq;
  start_date: string;
  end_date: string;
  active: boolean;
}

export interface MonthPoint {
  month: string;
  label: string;
  income: number;
  expense: number;
  income_s: string;
  expense_s: string;
  future: boolean;
}

export interface Goal {
  id: number;
  name: string;
  target: string;
  target_raw: string;
  deadline: string | null;
  account_ids: number[];
  accounts: string[];
  current: string;
  ratio: number;
  left: string | null;
  done: boolean;
  months_left: number | null;
  per_month: string | null;
  overdue: boolean;
}

export interface PlanParams {
  current: string;
  monthly: string;
  return: string;
  inflation: string;
  spend: string;
  withdrawal: string;
}

export interface LifePlanInput {
  id?: number | null;
  kind: 'house' | 'car' | 'other';
  name: string;
  target_month: string; // YYYY-MM or ''
  price: string;
  down_ratio: string;
  one_off: string;
  loan_rate: string;
  loan_years: string;
  grace_years: string;
  monthly_cost: string;
  rent_saved: string;
  account_ids: number[];
  active: boolean;
}

export interface LifePlan {
  id: number;
  kind: LifePlanInput['kind'];
  kind_label: string;
  name: string;
  target_month: string | null;
  active: boolean;
  price: string;
  need: string;
  down: string;
  one_off: string | null;
  saved: string;
  ratio: number;
  left: string | null;
  months_left: number | null;
  per_month: string | null;
  loan: {
    principal: string;
    payment: string;
    grace_payment: string | null;
    grace_months: number;
    years: string;
    total_interest: string;
  } | null;
  extra_monthly: string | null;
  burden: number | null;
  burden_level: AdviceLevel | null;
  account_ids: number[];
  accounts: string[];
  input: LifePlanInput;
}

export type AdviceLevel = 'warn' | 'note' | 'ok';
/** Plain text, or a TWD amount that privacy mode hides. */
export type Seg = string | { m: string };

export interface AdviceItem {
  key: string;
  level: AdviceLevel;
  title: string;
  detail: Seg[];
  action: Seg[] | null;
}

export interface Advice {
  items: AdviceItem[];
  thresholds: Record<string, string>;
}

export interface Plan {
  goals: Goal[];
  life_plans: LifePlan[];
  rebalance: {
    label: string;
    value: string;
    current: number;
    target: number;
    target_raw: number;
    trade: string;
    trade_sign: Sign;
    off: number;
  }[];
  fire: {
    params: PlanParams;
    auto: { current: string; monthly: string; spend: string };
    months_of_data: number;
    ready: boolean;
    target?: string;
    target_raw?: number;
    reached_now?: boolean;
    years?: number | null;
    year?: number | null;
    series?: { year: number; value: number }[];
    progress?: number;
    with_plans?: {
      names: string[];
      target: string;
      target_raw: number;
      years: number | null;
      year: number | null;
      delay_years: number | null;
      series: { year: number; value: number }[];
      marks: { name: string; year: number }[];
    } | null;
  };
}

export interface BacktestResult {
  symbol: string;
  name: string;
  currency: string;
  from: string;
  months: number;
  invested: string;
  value: string;
  gain: string;
  gain_sign: Sign;
  return_pct: string | null;
  xirr: string | null;
  series: { month: string; invested: number; value: number }[];
}

export type ComposerKind = 'expense' | 'income' | 'transfer' | 'buy' | 'sell' | 'cash_dividend' | 'more';
export type MoreKind = 'deposit' | 'withdraw' | 'stock_dividend' | 'split' | 'repay';

export interface TxFields {
  kind: ComposerKind;
  more: MoreKind;
  amount: string;
  category: string;
  account: string;
  to_account: string;
  symbol: string;
  qty: string;
  price: string;
  fee: string;
  tax: string;
  fx: string;
  total?: string; // 補登: the broker app's 總成本
  interest?: string; // 還款: the bank's interest when it differs from the computed one
  opening?: boolean; // 存入現金 that states the account's balance on that date (undefined: decided by the account)
  date: string;
  note: string;
  backfill?: boolean; // 買進 that only adds the holding (cash already reflects it)
  line?: string;
}

export interface AccountGroup {
  name: string;
  type: string;
  currencies: string[];
  total: string;
  archived: boolean;
}

export interface GroupInput {
  name: string;
  old_name?: string;
  type: string;
  currencies: string[];
}
