import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api';
import { categoryIcon, Icon } from '../lib/icons';
import { Money } from '../lib/privacy';
import type { ComposerKind, MoreKind, Preview, State, TxFields } from '../types';
import { Sheet } from './Panels';

// The composer builds the same one-line command the parser understands (services/quick.py), so
// preview, fees, validation and editing all go through the tested Python path.

const KINDS: [ComposerKind, string][] = [
  ['expense', '支出'],
  ['income', '收入'],
  ['transfer', '轉帳'],
  ['buy', '買進'],
  ['sell', '賣出'],
  ['cash_dividend', '股利'],
  ['more', '其他'],
];
const MORE: [MoreKind, string][] = [
  ['deposit', '存入現金'],
  ['withdraw', '提出現金'],
  ['stock_dividend', '股票股利'],
  ['split', '股票分割'],
  ['repay', '還款'],
];
const SPENDING = ['bank', 'cash', 'credit'];
const DEBT = ['credit', 'loan']; // an opening balance on these is what is owed
const CHIPS = 8;

export interface ComposerOpen {
  editId: number | null;
  fields?: TxFields;
  quick?: boolean; // start in the one-line field
  kind?: ComposerKind; // a new entry opened on this tab (e.g. 買進 from the empty 投資 card)
}

interface Props {
  state: State;
  open: ComposerOpen;
  onClose(): void;
  onSaved(state: State, message: string): void;
}

function blank(state: State, kind: ComposerKind = 'expense'): TxFields {
  return {
    kind,
    more: 'deposit',
    amount: '',
    category: '',
    account: defaultAccount(state, kind, 'deposit'),
    to_account: '',
    symbol: '',
    qty: '',
    price: '',
    fee: '',
    tax: '',
    fx: '',
    date: state.today,
    note: '',
    backfill: false,
  };
}

function defaultAccount(state: State, kind: ComposerKind, more: MoreKind): string {
  const live = state.accounts.filter(a => !a.archived);
  if (kind === 'more' && more === 'repay') return live.find(a => a.type === 'loan')?.name ?? '';
  const needsCash = kind === 'expense' || kind === 'income' || kind === 'transfer' || (kind === 'more' && (more === 'deposit' || more === 'withdraw'));
  if (!needsCash) return ''; // trades: let the symbol pick the broker account
  return (live.find(a => SPENDING.includes(a.type) && a.currency === 'TWD') ?? live.find(a => SPENDING.includes(a.type)) ?? live[0])?.name ?? '';
}

const clean = (v: string) => v.replace(/[,\s]/g, '');
const word = (v: string) => v.replace(/[\s@#]/g, '');

export function toLine(f: TxFields, today: string): string {
  const parts: string[] = [];
  const add = (...xs: (string | false | undefined)[]) => xs.forEach(x => x && parts.push(x));
  const acct = f.account && `@${f.account}`;
  switch (f.kind) {
    case 'expense':
    case 'income':
      add(f.kind === 'expense' ? '支出' : '收入', clean(f.amount), word(f.category), acct);
      break;
    case 'transfer':
      add('轉', clean(f.amount), acct, f.to_account && `@${f.to_account}`, f.fx && `匯 ${clean(f.fx)}`);
      break;
    case 'buy':
    case 'sell': {
      const total = f.kind === 'buy' && f.backfill && f.total ? clean(f.total) : '';
      add(
        f.kind === 'buy' ? (f.backfill ? '補' : '買') : '賣',
        word(f.symbol), clean(f.qty), clean(f.price), acct,
        // 總成本 already contains fees and the conversion, so it replaces them.
        total ? `總 ${total}` : f.fee && `費 ${clean(f.fee)}`,
        !total && f.tax && `稅 ${clean(f.tax)}`,
        !total && f.fx && `匯 ${clean(f.fx)}`,
      );
      break;
    }
    case 'cash_dividend':
      add('息', word(f.symbol), clean(f.amount), acct);
      break;
    case 'more':
      // 還款: the loan is `account`, the payer `to_account`; no amount = this month's scheduled payment.
      if (f.more === 'repay') add('還', clean(f.amount), acct, f.to_account && `@${f.to_account}`, f.interest && `利 ${clean(f.interest)}`);
      else if (f.more === 'deposit' || f.more === 'withdraw') add(f.more === 'deposit' ? '存' : '提', clean(f.amount), f.more === 'deposit' && f.opening && '期初', acct);
      else add(f.more === 'stock_dividend' ? '配股' : '拆', word(f.symbol), clean(f.qty), acct);
      break;
  }
  if (f.date && f.date !== today) parts.push(f.date);
  const line = parts.join(' ');
  return f.note.trim() ? `${line} # ${f.note.trim()}` : line;
}

/** Required fields the form is still missing (the one-line syntax is positional, so a gap would shift values). */
function missingFields(f: TxFields): string[] {
  const miss: string[] = [];
  const need = (v: string, label: string) => !clean(v) && miss.push(label);
  if (f.kind === 'buy' || f.kind === 'sell') {
    need(f.symbol, '股票代號');
    need(f.qty, f.backfill ? '總股數' : '股數');
    need(f.price, f.backfill ? '成交均價' : '成交價');
  } else if (f.kind === 'cash_dividend') {
    need(f.symbol, '股票代號');
    need(f.amount, '金額');
  } else if (f.kind === 'more' && f.more === 'repay') {
    need(f.account, '貸款帳戶');
  } else if (f.kind === 'more' && (f.more === 'stock_dividend' || f.more === 'split')) {
    need(f.symbol, '股票代號');
    need(f.qty, f.more === 'split' ? '分割比例' : '股數');
  } else {
    need(f.amount, '金額');
    if (f.kind === 'transfer') need(f.to_account, '轉到哪個帳戶');
  }
  return miss;
}

export function Composer({ state, open, onClose, onSaved }: Props) {
  const [f, setF] = useState<TxFields>(() => {
    const init = open.fields ?? blank(state, open.kind);
    // A debt opening is stored negative but typed as what is owed.
    const debt = init.opening && DEBT.includes(state.accounts.find(a => a.name === init.account)?.type ?? '');
    return debt ? { ...init, amount: init.amount.replace(/^-/, '') } : init;
  });
  const [quick, setQuick] = useState(open.quick && open.fields?.line ? open.fields.line : '');
  const [preview, setPreview] = useState<Preview>({ status: 'empty' });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [allCats, setAllCats] = useState(false);
  const [newCat, setNewCat] = useState(false);
  const [repeat, setRepeat] = useState(false);
  const firstField = useRef<HTMLInputElement>(null);
  const quickField = useRef<HTMLInputElement>(null);
  const seq = useRef(0);
  const editing = open.editId != null;

  // 期初: on by default for an account that has nothing recorded yet (its first balance).
  const openingAcct = state.accounts.find(a => a.name === f.account);
  const opening = f.opening ?? openingAcct?.cash_sign === 0;
  const owed = opening && f.kind === 'more' && f.more === 'deposit' && DEBT.includes(openingAcct?.type ?? '');
  const line = quick.trim() ? quick : toLine({ ...f, opening, amount: owed && clean(f.amount) ? `-${clean(f.amount).replace(/^-/, '')}` : f.amount }, state.today);
  const set = (patch: Partial<TxFields>) => {
    setF(prev => ({ ...prev, ...patch }));
    setError(null);
  };

  useEffect(() => {
    (open.quick ? quickField : firstField).current?.focus();
  }, [f.kind, f.more, open.quick]);

  const missing = quick.trim() ? [] : missingFields(f);
  const missingKey = missing.join('、');
  useEffect(() => {
    const n = ++seq.current;
    if (missingKey) {
      setPreview({ status: 'incomplete', title: null, message: `還缺：${missingKey}` });
      return;
    }
    const t = setTimeout(async () => {
      const r = await api.preview(line, open.editId);
      if (n === seq.current) setPreview(r.ok ? r.preview : { status: 'error', message: r.error });
    }, 140);
    return () => clearTimeout(t);
  }, [line, open.editId, missingKey]);

  function switchKind(kind: ComposerKind) {
    if (kind === f.kind) return;
    setF(prev => ({ ...blank(state, kind), date: prev.date, note: prev.note, amount: prev.amount }));
    setNewCat(false);
    setError(null);
  }

  async function submit() {
    if (busy) return;
    if (preview.status !== 'ready') {
      setError(preview.status === 'error' || preview.status === 'incomplete' ? preview.message : '還沒填完');
      return;
    }
    setBusy(true);
    const r = await api.commit(line, open.editId, canRepeat && repeat ? 'monthly' : null);
    setBusy(false);
    if (!r.ok) return setError(r.error);
    const month = f.date.slice(0, 7);
    const where = !quick.trim() && month !== state.today.slice(0, 7) ? `（記在 ${Number(month.slice(5))} 月，到「收支」切換月份查看）` : '';
    const again = canRepeat && repeat ? `，之後每月 ${Number(f.date.slice(8))} 日自動記` : '';
    onSaved(r.state, `${editing ? '已修改' : '已記錄'}：${preview.title}${where}${again}`);
  }

  async function remove() {
    if (open.editId == null) return;
    const r = await api.deleteTx(open.editId);
    if (!r.ok) return setError(r.error);
    onSaved(r.state, '已刪除');
  }

  const accounts = state.accounts.filter(a => !a.archived);
  const acctCur = accounts.find(a => a.name === f.account)?.currency;
  const ccy = acctCur && acctCur !== 'TWD' ? acctCur : 'NT$';
  const cats = state.categories.filter(c => c.kind === (f.kind === 'income' ? 'income' : 'expense'));
  const shownCats = allCats ? cats : cats.slice(0, CHIPS);
  const from = accounts.find(a => a.name === f.account);
  const to = accounts.find(a => a.name === f.to_account);
  const crossFx = from && to && from.currency !== to.currency && (from.currency === 'TWD' || to.currency === 'TWD');
  const repay = f.kind === 'more' && f.more === 'repay';
  const usesAmount =
    ['expense', 'income', 'transfer', 'cash_dividend'].includes(f.kind) || (f.kind === 'more' && (f.more === 'deposit' || f.more === 'withdraw' || repay));
  // 每月重複 makes a 週期性 rule from this entry (new entries only, and only from the form).
  const canRepeat = !editing && !quick.trim() && (['expense', 'income', 'transfer'].includes(f.kind) || repay);
  const guess = preview.status === 'ready' && !f.category ? preview.guessed_category : null;
  // Taiwan codes are digits (+ optional letter); anything with other letters or a suffix is a 複委託 trade.
  const foreign = !!f.symbol.trim() && !/^\d{4,6}[A-Za-z]?$/.test(f.symbol.trim());
  const usesSymbol = ['buy', 'sell', 'cash_dividend'].includes(f.kind) || (f.kind === 'more' && (f.more === 'stock_dividend' || f.more === 'split'));

  return (
    <Sheet title={editing ? '修改紀錄' : '記一筆'} onClose={onClose} wide>
      <form
        className="composer"
        onSubmit={e => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="seg" role="tablist" aria-label="類型">
          {KINDS.map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={f.kind === k} className={f.kind === k ? 'on' : ''} onClick={() => switchKind(k)}>
              {label}
            </button>
          ))}
        </div>

        {f.kind === 'more' && (
          <div className="chips" role="radiogroup" aria-label="其他類型">
            {MORE.map(([k, label]) => (
              <button
                key={k}
                type="button"
                role="radio"
                aria-checked={f.more === k}
                className={`chip ${f.more === k ? 'on' : ''}`}
                onClick={() => set({ more: k, account: defaultAccount(state, 'more', k), to_account: k === 'repay' ? defaultAccount(state, 'expense', k) : '', ...(k === 'repay' ? { amount: '' } : {}) })}
              >
                {label}
              </button>
            ))}
          </div>
        )}

        {usesSymbol && (
          <SymbolField
            inputRef={usesAmount && !['cash_dividend'].includes(f.kind) ? undefined : firstField}
            value={f.symbol}
            onChange={symbol => set({ symbol })}
            onPick={(symbol, close) => set({ symbol, price: f.price || (['buy', 'sell'].includes(f.kind) && close ? clean(close) : f.price) })}
            onResolve={close => {
              // An exact code match: offer the latest close as the price (only if none typed yet).
              // (Not when backfilling: today's price would be wrong for an old purchase.)
              if (close && (f.kind === 'buy' || f.kind === 'sell')) setF(prev => (prev.price || prev.backfill ? prev : { ...prev, price: clean(close) }));
            }}
          />
        )}

        {usesAmount && (
          <label className="amount-field">
            <span className="ccy">{f.kind === 'cash_dividend' ? '實收' : ccy}</span>
            <input
              ref={f.kind === 'cash_dividend' ? undefined : firstField}
              className="num"
              inputMode="decimal"
              placeholder={repay ? '空白＝這期月付' : '0'}
              value={f.amount}
              aria-label="金額"
              onChange={e => set({ amount: e.target.value })}
            />
          </label>
        )}

        {f.kind === 'more' && f.more === 'deposit' && (
          <label className="backfill">
            <input type="checkbox" checked={opening} onChange={e => set({ opening: e.target.checked })} />
            <span>
              {owed ? '這是帳戶在這天的欠款（期初）' : '這是帳戶在這天的餘額（期初）'}
              <span className="muted tiny">
                　
                {owed
                  ? '金額填目前欠多少（含還沒出帳的刷卡）。之後補登這天以前的刷卡，會自動吸收，欠款不會重複計算'
                  : '建帳用。之後補登這天以前的收入或支出，這筆會自動扣掉或加回，餘額不會重複計算'}
              </span>
            </span>
          </label>
        )}

        {f.kind === 'buy' && (
          <label className="backfill">
            <input type="checkbox" checked={!!f.backfill} onChange={e => set({ backfill: e.target.checked, price: e.target.checked ? '' : f.price, total: '' })} />
            <span>
              補登過去買的股票
              <span className="muted tiny">　帳戶現金已經是現在的餘額，這筆只記持股和成本，不再扣款；日期選當初買進那天、成交價填當時的價格</span>
            </span>
          </label>
        )}

        {(f.kind === 'buy' || f.kind === 'sell') && (
          <div className="field-row">
            <Field label={f.backfill ? '總股數' : '股數'} hint={foreign ? undefined : '1 張 = 1,000 股'}>
              <input className="num" inputMode="decimal" value={f.qty} placeholder={foreign ? '100' : '1000'} onChange={e => set({ qty: e.target.value })} />
            </Field>
            <Field label={f.backfill ? '成交均價' : '成交價'}>
              <input className="num" inputMode="decimal" value={f.price} placeholder="0.00" onChange={e => set({ price: e.target.value })} />
            </Field>
            {!(f.backfill && f.total) && (
              <Field label="手續費" hint={foreign && !/\.HK$/i.test(f.symbol.trim()) ? '填實際金額' : '空白＝自動計算'}>
                <input className="num" inputMode="decimal" value={f.fee} placeholder={foreign && !/\.HK$/i.test(f.symbol.trim()) ? '0' : '自動'} onChange={e => set({ fee: e.target.value })} />
              </Field>
            )}
            {foreign && !(f.backfill && f.total) && (
              <Field label="成交匯率" hint="填對帳單上的">
                <input className="num" inputMode="decimal" value={f.fx} placeholder="自動" onChange={e => set({ fx: e.target.value })} />
              </Field>
            )}
          </div>
        )}

        {f.kind === 'buy' && f.backfill && (
          <Field label="總成本" hint="國泰 App 庫存的「總成本」，已含手續費和換匯；填了就不用填手續費、匯率">
            <input className="num" inputMode="decimal" value={f.total ?? ''} placeholder="可不填（建議填）" onChange={e => set({ total: e.target.value })} />
          </Field>
        )}

        {f.kind === 'more' && (f.more === 'stock_dividend' || f.more === 'split') && (
          <div className="field-row">
            <Field label={f.more === 'split' ? '1 股變成幾股' : '配發股數'}>
              <input className="num" inputMode="decimal" value={f.qty} placeholder={f.more === 'split' ? '10' : '50'} onChange={e => set({ qty: e.target.value })} />
            </Field>
          </div>
        )}

        {(f.kind === 'expense' || f.kind === 'income') && (
          <div className="field">
            <span className="field-label">分類</span>
            <div className="chips">
              {shownCats.map(c => (
                <button
                  key={c.id}
                  type="button"
                  className={`chip ${f.category === c.name ? 'on' : ''} ${guess === c.name ? 'guess' : ''}`}
                  title={guess === c.name ? '依過去同樣備註的紀錄' : undefined}
                  onClick={() => set({ category: f.category === c.name ? '' : c.name })}
                >
                  <Icon name={categoryIcon(c.name, f.kind)} size={14} />
                  {c.name}
                </button>
              ))}
              {guess && !shownCats.some(c => c.name === guess) && (
                <button type="button" className="chip guess" onClick={() => set({ category: guess })}>
                  <Icon name={categoryIcon(guess, f.kind)} size={14} />
                  {guess}
                </button>
              )}
              {!allCats && cats.length > CHIPS && (
                <button type="button" className="chip ghost" onClick={() => setAllCats(true)}>
                  更多…
                </button>
              )}
              {newCat ? (
                <input
                  className="chip-input"
                  autoFocus
                  placeholder="新分類名稱"
                  value={cats.some(c => c.name === f.category) ? '' : f.category}
                  onChange={e => set({ category: word(e.target.value) })}
                />
              ) : (
                <button type="button" className="chip ghost" onClick={() => setNewCat(true)}>
                  ＋ 新分類
                </button>
              )}
            </div>
          </div>
        )}

        {repay ? (
          <>
            <div className="field-row two">
              <Field label="還哪一筆貸款">
                <AccountSelect accounts={accounts.filter(a => a.type === 'loan')} value={f.account} onChange={account => set({ account })} placeholder="選擇貸款" />
              </Field>
              <Field label="從哪個帳戶付">
                <AccountSelect accounts={accounts.filter(a => a.type !== 'loan')} value={f.to_account} onChange={to_account => set({ to_account })} />
              </Field>
            </div>
            <div className="field-row two">
              <Field label="利息" hint="空白＝剩餘本金 × 年利率 ÷ 12">
                <input className="num" inputMode="decimal" value={f.interest ?? ''} placeholder="自動" onChange={e => set({ interest: e.target.value })} />
              </Field>
              <Field label="日期">
                <input type="date" value={f.date} max={state.today} onChange={e => set({ date: e.target.value || state.today })} />
              </Field>
            </div>
            {accounts.every(a => a.type !== 'loan') && <p className="muted small">先到「帳戶」新增一個「貸款」帳戶。</p>}
          </>
        ) : f.kind === 'transfer' ? (
          <>
            <div className="field-row two">
              <Field label="從">
                <AccountSelect accounts={accounts} value={f.account} onChange={account => set({ account })} />
              </Field>
              <Field label="轉到">
                <AccountSelect accounts={accounts} value={f.to_account} onChange={to_account => set({ to_account })} placeholder="選擇帳戶" />
              </Field>
            </div>
            <div className="field-row two">
              {crossFx && (
                <Field label="匯率" hint="空白＝當天匯率">
                  <input className="num" inputMode="decimal" value={f.fx} placeholder="自動" onChange={e => set({ fx: e.target.value })} />
                </Field>
              )}
              <Field label="日期">
                <input type="date" value={f.date} max={state.today} onChange={e => set({ date: e.target.value || state.today })} />
              </Field>
            </div>
          </>
        ) : (
          <div className="field-row two">
            <Field label="帳戶">
              <AccountSelect
                accounts={accounts}
                value={f.account}
                onChange={account => set({ account })}
                placeholder={usesSymbol ? '自動（依代號）' : undefined}
              />
            </Field>
            <Field label="日期">
              <input type="date" value={f.date} max={state.today} onChange={e => set({ date: e.target.value || state.today })} />
            </Field>
          </div>
        )}

        <Field label="備註">
          <input value={f.note} placeholder="可不填" onChange={e => set({ note: e.target.value })} />
        </Field>

        {canRepeat && (
          <label className="backfill">
            <input type="checkbox" checked={repeat} onChange={e => setRepeat(e.target.checked)} />
            <span>
              每月重複
              <span className="muted tiny">　之後每月 {Number(f.date.slice(8))} 日自動記一筆；在「收支 → 週期性」可以修改或停用</span>
            </span>
          </label>
        )}

        <div className={`composer-preview ${preview.status}`} aria-live="polite">
          <PreviewText preview={error ? { status: 'error', message: error } : preview} />
        </div>

        <div className="composer-actions">
          <label className="quick">
            <span className="muted tiny">或直接打一行</span>
            <input
              ref={quickField}
              value={quick}
              placeholder="支出 120 午餐 @台新"
              spellCheck={false}
              onChange={e => {
                setQuick(e.target.value);
                setError(null);
              }}
            />
          </label>
          {editing && (
            <button type="button" className="quiet danger" onClick={remove}>
              刪除
            </button>
          )}
          <button type="button" className="quiet" onClick={onClose}>
            取消
          </button>
          <button type="submit" className="primary" disabled={busy}>
            {editing ? '儲存修改' : '記錄'} <kbd>↵</kbd>
          </button>
        </div>
      </form>
    </Sheet>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">
        {label}
        {hint && <span className="muted tiny">　{hint}</span>}
      </span>
      {children}
    </label>
  );
}

/** Accounts, with each multi-currency account listed once and a currency menu beside it. */
function AccountSelect(props: { accounts: State['accounts']; value: string; onChange(v: string): void; placeholder?: string }) {
  const current = props.accounts.find(a => a.name === props.value);
  const groupName = current?.group_name ?? null;
  const singles = props.accounts.filter(a => !a.group_name);
  const groups = [...new Set(props.accounts.filter(a => a.group_name).map(a => a.group_name!))];
  const parts = groupName ? props.accounts.filter(a => a.group_name === groupName) : [];
  return (
    <span className="picker">
      <select
        value={groupName ? `group:${groupName}` : props.value}
        onChange={e => {
          const v = e.target.value;
          if (!v.startsWith('group:')) return props.onChange(v);
          const list = props.accounts.filter(a => a.group_name === v.slice(6));
          props.onChange((list.find(a => a.currency === 'USD') ?? list[0])?.name ?? '');
        }}
      >
        {(props.placeholder || !props.value) && <option value="">{props.placeholder ?? '選擇帳戶'}</option>}
        {singles.map(a => (
          <option key={a.id} value={a.name}>
            {a.name}（{a.type_label}
            {a.currency !== 'TWD' ? `，${a.currency}` : ''}）
          </option>
        ))}
        {groups.map(g => (
          <option key={g} value={`group:${g}`}>
            {g}（多幣別）
          </option>
        ))}
      </select>
      {groupName && (
        <select value={props.value} aria-label="幣別" className="ccy-select" onChange={e => props.onChange(e.target.value)}>
          {parts.map(a => (
            <option key={a.id} value={a.name}>
              {a.currency}
            </option>
          ))}
        </select>
      )}
    </span>
  );
}

/** Code field with suggestions from the security list (and Yahoo for US tickers). */
function SymbolField(props: {
  value: string;
  onChange(v: string): void;
  onPick(symbol: string, close: string | null): void;
  onResolve?(close: string | null): void;
  inputRef?: React.Ref<HTMLInputElement>;
}) {
  const [results, setResults] = useState<Extract<Preview, { status: 'lookup' }>['results']>([]);
  const [focused, setFocused] = useState(false);
  const [name, setName] = useState('');
  const q = props.value.trim();
  useEffect(() => {
    if (!q) {
      setResults([]);
      setName('');
      return;
    }
    let live = true;
    const t = setTimeout(async () => {
      const r = await api.preview(q, null);
      if (!live) return;
      const found = r.ok && r.preview.status === 'lookup' ? r.preview.results : [];
      setResults(found);
      const hit = found.find(x => x.symbol === q.toUpperCase());
      setName(hit?.name ?? '');
      if (hit) props.onResolve?.(hit.close);
    }, 160);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [q]);
  const exact = useMemo(() => results.some(r => r.symbol === q.toUpperCase()), [results, q]);
  return (
    <div className="field symbol-field">
      <span className="field-label">股票代號{name && <span className="muted">　{name}</span>}</span>
      <input
        ref={props.inputRef}
        value={props.value}
        placeholder="2330、0050、VOO、港股 0700.HK，或打名稱"
        spellCheck={false}
        autoComplete="off"
        onChange={e => props.onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setTimeout(() => setFocused(false), 120)}
      />
      {focused && results.length > 0 && !(exact && results.length === 1) && (
        <ul className="suggest" role="listbox">
          {results.map(r => (
            <li key={r.symbol}>
              <button
                type="button"
                onMouseDown={e => e.preventDefault()}
                onClick={() => {
                  props.onPick(r.symbol, r.close);
                  setFocused(false);
                }}
              >
                <span className="code">{r.symbol}</span>
                <span className="ellipsis">{r.name}</span>
                <span className="num muted">{r.close ?? ''}</span>
                {r.held && <span className="muted tiny">持有 {r.held}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PreviewText({ preview }: { preview: Preview }) {
  switch (preview.status) {
    case 'empty':
      return <span className="muted">填好之後這裡會顯示要記錄的內容</span>;
    case 'incomplete':
      return (
        <span className="muted">
          {preview.title && <strong>{preview.title}　</strong>}
          {preview.message}
        </span>
      );
    case 'error':
      return <span className="warn">{preview.message}</span>;
    case 'lookup':
      return <span className="muted">一行輸入要用 支出、收入、轉、買、賣、息… 開頭</span>;
    case 'ready':
      return (
        <>
          <span className="pv-main">
            <strong>{preview.title}</strong>
            <span className="muted">{preview.parts.join('，')}</span>
          </span>
          {preview.total && <Money className="num pv-total" value={preview.total} />}
        </>
      );
  }
}
