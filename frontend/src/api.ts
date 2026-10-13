// Typed access to the Python side (pywebview js_api, see src/portfolio_ledger/api.py).
import type {
  AccountInput, Advice, BacktestResult, GroupInput, LifePlanInput, MonthReport, Plan, PlanParams, Preview, RecurringFreq,
  RecurringInput, RecurringRule, Settings, State, TxFields, YearReport,
} from './types';

type Fail = { ok: false; error: string };
type Res<T> = ({ ok: true } & T) | Fail;

interface PyApi {
  get_state(): Promise<Res<{ state: State }>>;
  preview(text: string, editId: number | null): Promise<Res<{ preview: Preview }>>;
  commit(text: string, editId: number | null, repeat: RecurringFreq | null): Promise<Res<{ id: number; state: State }>>;
  delete_tx(id: number): Promise<Res<{ state: State }>>;
  tx_line(id: number): Promise<Res<{ line: string }>>;
  tx_fields(id: number): Promise<Res<{ fields: TxFields }>>;
  save_account(data: AccountInput): Promise<Res<{ id: number; state: State }>>;
  delete_account(id: number): Promise<Res<{ state: State }>>;
  save_group(data: GroupInput): Promise<Res<{ state: State }>>;
  delete_group(name: string): Promise<Res<{ state: State }>>;
  save_settings(values: Partial<Settings>): Promise<Res<{ state: State }>>;
  get_month(month: string | null): Promise<Res<{ month: MonthReport }>>;
  set_budget(categoryId: number, amount: string, month: string | null): Promise<Res<{ month: MonthReport }>>;
  set_total_budget(amount: string, month: string | null): Promise<Res<{ month: MonthReport }>>;
  get_year(year: number | null): Promise<Res<{ year: YearReport }>>;
  get_recurring(): Promise<Res<{ rules: RecurringRule[] }>>;
  recurring_backfill(data: RecurringInput): Promise<Res<{ count: number }>>;
  save_recurring(data: RecurringInput): Promise<Res<{ posted: number; rules: RecurringRule[]; state: State }>>;
  delete_recurring(id: number): Promise<Res<{ rules: RecurringRule[]; state: State }>>;
  get_plan(): Promise<Res<{ plan: Plan }>>;
  save_plan(values: Partial<PlanParams>): Promise<Res<{ plan: Plan }>>;
  save_targets(values: Record<string, string>): Promise<Res<{ plan: Plan }>>;
  save_goal(data: GoalInput): Promise<Res<{ plan: Plan }>>;
  delete_goal(id: number): Promise<Res<{ plan: Plan }>>;
  save_life_plan(data: LifePlanInput): Promise<Res<{ plan: Plan }>>;
  delete_life_plan(id: number): Promise<Res<{ plan: Plan }>>;
  get_advice(): Promise<Res<{ advice: Advice }>>;
  save_advice_thresholds(values: Record<string, string>): Promise<Res<{ advice: Advice }>>;
  backtest(symbol: string, start: string, amount: string): Promise<Res<{ result: BacktestResult }>>;
  refresh(): Promise<Res<object>>;
  export_csv(): Promise<Res<{ path: string }>>;
  backup(): Promise<Res<{ path: string }>>;
}

declare global {
  interface Window {
    pywebview?: { api: PyApi };
    /** Called by Python (app.py) when quotes were refreshed in the background. */
    ledgerChanged?: () => void;
  }
}

export interface GoalInput {
  id?: number;
  name: string;
  target: string;
  deadline: string;
  account_ids: number[];
}

let ready: Promise<PyApi> | null = null;

/** Resolves once pywebview has injected its API (it may already be there). */
function py(): Promise<PyApi> {
  if (!ready) {
    ready = new Promise(resolve => {
      if (window.pywebview?.api) return resolve(window.pywebview.api);
      window.addEventListener('pywebviewready', () => resolve(window.pywebview!.api), { once: true });
    });
  }
  return ready;
}

export const api = {
  state: async () => (await py()).get_state(),
  preview: async (text: string, editId: number | null) => (await py()).preview(text, editId),
  commit: async (text: string, editId: number | null, repeat: RecurringFreq | null = null) =>
    (await py()).commit(text, editId, repeat),
  deleteTx: async (id: number) => (await py()).delete_tx(id),
  txLine: async (id: number) => (await py()).tx_line(id),
  txFields: async (id: number) => (await py()).tx_fields(id),
  saveAccount: async (data: AccountInput) => (await py()).save_account(data),
  deleteAccount: async (id: number) => (await py()).delete_account(id),
  saveGroup: async (data: GroupInput) => (await py()).save_group(data),
  deleteGroup: async (name: string) => (await py()).delete_group(name),
  saveSettings: async (values: Partial<Settings>) => (await py()).save_settings(values),
  month: async (month: string | null) => (await py()).get_month(month),
  setBudget: async (id: number, amount: string, month: string | null) => (await py()).set_budget(id, amount, month),
  setTotalBudget: async (amount: string, month: string | null) => (await py()).set_total_budget(amount, month),
  year: async (year: number | null) => (await py()).get_year(year),
  recurring: async () => (await py()).get_recurring(),
  recurringBackfill: async (data: RecurringInput) => (await py()).recurring_backfill(data),
  saveRecurring: async (data: RecurringInput) => (await py()).save_recurring(data),
  deleteRecurring: async (id: number) => (await py()).delete_recurring(id),
  plan: async () => (await py()).get_plan(),
  savePlan: async (values: Partial<PlanParams>) => (await py()).save_plan(values),
  saveTargets: async (values: Record<string, string>) => (await py()).save_targets(values),
  saveGoal: async (data: GoalInput) => (await py()).save_goal(data),
  deleteGoal: async (id: number) => (await py()).delete_goal(id),
  saveLifePlan: async (data: LifePlanInput) => (await py()).save_life_plan(data),
  deleteLifePlan: async (id: number) => (await py()).delete_life_plan(id),
  advice: async () => (await py()).get_advice(),
  saveAdviceThresholds: async (values: Record<string, string>) => (await py()).save_advice_thresholds(values),
  backtest: async (symbol: string, start: string, amount: string) => (await py()).backtest(symbol, start, amount),
  refresh: async () => (await py()).refresh(),
  exportCsv: async () => (await py()).export_csv(),
  backup: async () => (await py()).backup(),
};
