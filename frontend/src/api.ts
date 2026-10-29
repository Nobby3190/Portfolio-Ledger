// Typed access to the Python side (pywebview js_api, see src/portfolio_ledger/api.py).
import type {
  AccountInput, Advice, Alerts, Dividends, Fundamentals, Note, NoteInput, WatchRow, GroupInput, LifePlanInput, MonthReport, Plan, PlanParams, Preview, RecurringFreq,
  RecurringInput, RecurringRule, Settings, State, TxFields, YearReport,
} from './types';

type Fail = { ok: false; error: string };
type Res<T> = ({ ok: true } & T) | Fail;

interface PyApi {
  get_state(): Promise<Res<{ state: State }>>;
  unlock(): Promise<{ ok: true } | (Fail & { cancelled?: boolean })>;
  preview(text: string, editId: number | null): Promise<Res<{ preview: Preview }>>;
  commit(text: string, editId: number | null, repeat: RecurringFreq | null): Promise<Res<{ id: number | null; posted?: number; state: State }>>;
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
  rename_category(id: number, name: string): Promise<Res<{ state: State }>>;
  set_category_parent(id: number, parentId: number | null): Promise<Res<{ state: State }>>;
  add_category(kind: 'income' | 'expense', name: string): Promise<Res<{ state: State }>>;
  set_category_color(id: number, color: string | null): Promise<Res<{ state: State }>>;
  set_category_archived(id: number, archived: boolean): Promise<Res<{ state: State }>>;
  move_category(id: number, step: number): Promise<Res<{ state: State }>>;
  delete_category(id: number): Promise<Res<{ state: State }>>;
  get_year(year: number | null): Promise<Res<{ year: YearReport }>>;
  get_recurring(): Promise<Res<{ rules: RecurringRule[] }>>;
  recurring_backfill(data: RecurringInput): Promise<Res<{ count: number }>>;
  save_recurring(data: RecurringInput): Promise<Res<{ posted: number; rules: RecurringRule[]; state: State }>>;
  delete_recurring(id: number): Promise<Res<{ rules: RecurringRule[]; state: State }>>;
  get_plan(): Promise<Res<{ plan: Plan }>>;
  save_plan(values: Partial<PlanParams>): Promise<Res<{ plan: Plan }>>;
  save_targets(values: Record<string, string>): Promise<Res<{ plan: Plan }>>;
  save_life_plan(data: LifePlanInput): Promise<Res<{ plan: Plan }>>;
  delete_life_plan(id: number): Promise<Res<{ plan: Plan }>>;
  get_advice(): Promise<Res<{ advice: Advice }>>;
  save_advice_thresholds(values: Record<string, string>): Promise<Res<{ advice: Advice }>>;
  get_dividends(): Promise<Res<{ dividends: Dividends }>>;
  get_fundamentals(symbol: string, force: boolean): Promise<Res<{ fundamentals: Fundamentals }>>;
  copy_text(text: string): Promise<Res<object>>;
  copy_holdings(): Promise<Res<{ text: string }>>;
  export_holdings_md(): Promise<Res<{ path: string }>>;
  get_watchlist(): Promise<Res<{ watchlist: WatchRow[] }>>;
  add_watch(symbol: string): Promise<Res<{ symbol: string; watchlist: WatchRow[] }>>;
  remove_watch(symbol: string): Promise<Res<{ watchlist: WatchRow[] }>>;
  get_note(symbol: string): Promise<Res<{ note: Note | null }>>;
  save_note(data: NoteInput): Promise<Res<{ note: Note | null }>>;
  mark_reviewed(symbol: string): Promise<Res<{ note: Note | null }>>;
  get_alerts(): Promise<Res<{ alerts: Alerts }>>;
  dismiss_alert(key: string): Promise<Res<{ alerts: Alerts }>>;
  save_alert_settings(values: Partial<Record<'day_pct' | 'week_pct' | 'watchlist' | 'card_days' | 'fx_pct' | 'notify', string | boolean>>): Promise<Res<{ alerts: Alerts }>>;
  refresh(): Promise<Res<object>>;
  export_csv(): Promise<Res<{ path: string }>>;
  backup(): Promise<Res<{ path: string }>>;
}

declare global {
  interface Window {
    pywebview?: { api: PyApi };
    /** Called by Python (app.py) when quotes were refreshed in the background. */
    ledgerChanged?: () => void;
    /** Called by Python (app.py) when the screen locks or the Mac sleeps: hide the amounts again. */
    ledgerLock?: () => void;
  }
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
  unlock: async () => (await py()).unlock(),
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
  renameCategory: async (id: number, name: string) => (await py()).rename_category(id, name),
  setCategoryParent: async (id: number, parentId: number | null) => (await py()).set_category_parent(id, parentId),
  addCategory: async (kind: 'income' | 'expense', name: string) => (await py()).add_category(kind, name),
  setCategoryColor: async (id: number, color: string | null) => (await py()).set_category_color(id, color),
  setCategoryArchived: async (id: number, archived: boolean) => (await py()).set_category_archived(id, archived),
  moveCategory: async (id: number, step: number) => (await py()).move_category(id, step),
  deleteCategory: async (id: number) => (await py()).delete_category(id),
  year: async (year: number | null) => (await py()).get_year(year),
  recurring: async () => (await py()).get_recurring(),
  recurringBackfill: async (data: RecurringInput) => (await py()).recurring_backfill(data),
  saveRecurring: async (data: RecurringInput) => (await py()).save_recurring(data),
  deleteRecurring: async (id: number) => (await py()).delete_recurring(id),
  plan: async () => (await py()).get_plan(),
  savePlan: async (values: Partial<PlanParams>) => (await py()).save_plan(values),
  saveTargets: async (values: Record<string, string>) => (await py()).save_targets(values),
  saveLifePlan: async (data: LifePlanInput) => (await py()).save_life_plan(data),
  deleteLifePlan: async (id: number) => (await py()).delete_life_plan(id),
  advice: async () => (await py()).get_advice(),
  saveAdviceThresholds: async (values: Record<string, string>) => (await py()).save_advice_thresholds(values),
  dividends: async () => (await py()).get_dividends(),
  fundamentals: async (symbol: string, force = false) => (await py()).get_fundamentals(symbol, force),
  copyText: async (text: string) => (await py()).copy_text(text),
  copyHoldings: async () => (await py()).copy_holdings(),
  exportHoldingsMd: async () => (await py()).export_holdings_md(),
  watchlist: async () => (await py()).get_watchlist(),
  addWatch: async (symbol: string) => (await py()).add_watch(symbol),
  removeWatch: async (symbol: string) => (await py()).remove_watch(symbol),
  note: async (symbol: string) => (await py()).get_note(symbol),
  saveNote: async (data: NoteInput) => (await py()).save_note(data),
  markReviewed: async (symbol: string) => (await py()).mark_reviewed(symbol),
  alerts: async () => (await py()).get_alerts(),
  dismissAlert: async (key: string) => (await py()).dismiss_alert(key),
  saveAlertSettings: async (values: Partial<Record<'day_pct' | 'week_pct' | 'watchlist' | 'card_days' | 'fx_pct' | 'notify', string | boolean>>) =>
    (await py()).save_alert_settings(values),
  refresh: async () => (await py()).refresh(),
  exportCsv: async () => (await py()).export_csv(),
  backup: async () => (await py()).backup(),
};
