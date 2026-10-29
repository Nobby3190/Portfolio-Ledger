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
  dividends_ttm: string | null; // last 12 months, TWD
  yield_on_cost: string | null; // last 12 months ÷ cost
  xirr: string | null; // annualized; null under a year of history
  day_change: string;
  day_pct: string | null;
  sign: Sign;
  day_sign: Sign;
  weight: number;
  accounts: string[];
  tx_ids: number[];
  dca: HoldingDca | null; // 定期定額 rules for this stock and the buys they posted
}

export interface HoldingDca {
  rules: { id: number; amount: string; freq_label: string; next_date: string | null; active: boolean; error: string | null }[];
  count: number;
  first_date: string | null;
  invested: string | null; // TWD, fees included
  avg_price: string | null;
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
  dca: boolean; // posted by a 定期定額 rule
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
  statement_day: number | null; // credit cards: 結帳日, 扣款日 (day of month)
  pay_day: number | null;
  autopay: string | null; // the account the card's bill is paid from automatically
  archived: boolean;
  color: string | null; // picked by hand; null = from the bank/broker in the name
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
  privacy_lock: '0' | '1'; // open with the amounts hidden; showing them takes Touch ID or the password
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
  xirr: string | null; // annualized return of all holdings; null under a year of history
  allocation: { label: string; value: string; ratio: number }[];
  allocation_groups: {
    groups: { key: 'invest' | 'cash'; label: string; value: string; ratio: number; items: { label: string; value: string; ratio: number }[] }[];
    debts: { label: string; value: string }[];
    debt_total: string | null;
  };
  history: { date: string; total: string; holdings: string | null }[]; // holdings: null where an old snapshot can't tell
  holdings: Holding[];
  holdings_value: string;
  holdings_unrealized: string;
  holdings_unrealized_sign: Sign;
  holdings_unrealized_pct: string | null; // on the open positions' cost, like each row's
  closed: Closed[];
  transactions: TxRow[];
  categories: Category[];
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
  statement_day?: string;
  pay_day?: string;
  autopay?: string;
  archived?: boolean;
  color?: string;
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
  categories: MonthCategory[];
  income_categories: { name: string; amount: string }[];
  trend: MonthPoint[]; // 6 months ending at this month at the latest (the chart)
  tabs: MonthPoint[]; // the trend, plus the months still to come this year when it ends at this month
  is_future: boolean;
  has_data: boolean;
}

export interface Category {
  id: number;
  name: string;
  kind: 'income' | 'expense';
  uses: number; // last 90 days (the composer's order)
  count: number; // all time
  parent_id: number | null; // 子類別: rolls up into this one
  sort: number;
  color: string | null; // a tone name (sky, plum…) picked in 管理分類; null = from the name
  archived: boolean; // listed last; not offered as a composer chip
}

export interface MonthCategory {
  id: number;
  name: string;
  spent: string;
  budget: string | null;
  budget_raw: string;
  budget_ratio: number | null;
  share: number; // of the month's spending; a subcategory's, of its parent's
  last: string | null;
  delta: string | null;
  delta_sign: Sign;
  own?: boolean; // the parent's own part (消費（未細分）)
  children?: MonthCategory[]; // 子類別, parent's totals include them
}

export interface YearCategory {
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
  own?: boolean;
  children?: YearCategory[];
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
  categories: YearCategory[];
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
  scope: PlanScope;
  account_ids: number[]; // used when scope is 'accounts'
  active: boolean;
}

/** What a goal counts as saved (DESIGN.md 規劃視圖「追蹤範圍」); 'total' shares the net worth with the other plans. */
export type PlanScope = 'cash' | 'cash_deposit' | 'total' | 'accounts';

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
  overdue: boolean;
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
  scope: PlanScope;
  scope_label: string;
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

/** 投資筆記 (tracking.note_view): the user's own words, one per symbol. */
export interface Note {
  symbol: string;
  thesis: string;
  red_lines: string[];
  band_low: string | null;
  band_high: string | null;
  review_months: number | null;
  last_review: string | null;
  review_due: string | null;
  updated_at: string;
  input: NoteInput;
}

export interface NoteInput {
  symbol: string;
  thesis: string;
  red_lines: string; // one per line
  band_low: string;
  band_high: string;
  review_months: string;
  last_review: string;
}

/** 自選股 row (tracking.watchlist). */
export interface WatchRow {
  symbol: string;
  name: string;
  market: string;
  currency: string;
  kind: string;
  close: string | null;
  close_date: string | null;
  day_pct: string | null;
  day_sign: Sign;
  week_pct: string | null;
  week_sign: Sign;
  band: string | null;
  band_where: string | null;
  band_side: -1 | 0 | 1;
  note: Note | null;
}

export interface AlertItem extends AdviceItem {
  symbol: string;
  name: string;
  held: boolean;
  red_lines: string[];
  kind: 'dismiss' | 'review'; // review: goes away with 標記為已檢查
}

export interface Alerts {
  items: AlertItem[];
  settings: { day_pct: string; week_pct: string; watchlist: boolean; card_days: string; fx_pct: string; notify: boolean };
}

/** 財報快照 (tracking.fundamentals_report): public numbers and the 7 去劣 checks; never a verdict. */
export interface Fundamentals {
  symbol: string;
  name: string;
  available: boolean;
  reason?: string; // when not available (ETF, 港股…)
  currency?: string;
  unit?: string; // 台幣億, 美元百萬
  table?: { years: string[]; rows: { key: string; label: string; values: (string | null)[] }[] } | null;
  checks?: { key: string; label: string; rule: string; value: string | null; status: 'pass' | 'fail' | 'na'; note: string }[];
  valuation?: { pe: string | null; pb: string | null; dividend_yield: string | null } | null;
  source?: string | null;
  fetched_at?: string | null;
  error?: string | null;
  commands?: { label: string; text: string }[];
}

/** 股利 card (finance.dividend_report). */
export interface Dividends {
  has: boolean;
  ttm: string;
  ytd: string;
  yield_on_cost: string | null;
  cover: string | null; // last 12 months of dividends ÷ a year of spending
  by_symbol: { symbol: string; name: string; amount: string; ratio: number; held: boolean }[];
  upcoming: {
    symbol: string;
    name: string;
    ex_date: string;
    pay_date: string | null;
    cash: string | null; // per share; null = not announced
    currency: string;
    estimate: string | null;
  }[];
}

export interface Plan {
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
  dca?: boolean; // 買進 of a fixed amount at the close (定額)
  gross?: boolean; // 股利 typed before 預扣稅／二代健保
  line?: string;
}

export interface AccountGroup {
  name: string;
  type: string;
  color: string | null;
  currencies: string[];
  total: string;
  archived: boolean;
}

export interface GroupInput {
  name: string;
  old_name?: string;
  type: string;
  currencies: string[];
  color?: string;
}
