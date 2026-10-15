import { type CSSProperties, type ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { accountIcon, Icon, type IconName } from '../lib/icons';
import { accountColor, INSTITUTIONS, type Institution, type InstitutionKind, institutionOf, SWATCHES } from '../lib/institutions';
import { useReducedMotion } from '../lib/motion';
import { Money } from '../lib/privacy';
import type { AccountGroup, AccountInput, AccountRow, GroupInput, Settings, State } from '../types';

export function Sheet({
  title,
  onClose,
  children,
  wide = false,
  size,
  actions,
}: {
  title: string;
  onClose(): void;
  children: ReactNode;
  wide?: boolean;
  size?: 'xwide';
  actions?: ReactNode; // beside 關閉, e.g. a HelpTip
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const [closing, setClosing] = useState(false);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  // Esc, the scrim and 關閉 fade the sheet out first; callers that close it themselves (after saving) don't wait.
  const requestClose = useCallback(() => {
    if (reduce) return closeRef.current();
    setClosing(true);
    setTimeout(() => closeRef.current(), 150);
  }, [reduce]);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    // Leave focus alone if a field inside (autoFocus) already took it.
    if (!ref.current?.contains(document.activeElement)) ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && requestClose();
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      prev?.focus?.();
    };
  }, [requestClose]);
  return (
    <div className={`scrim ${closing ? 'closing' : ''}`} onMouseDown={e => e.target === e.currentTarget && requestClose()}>
      <div className={`sheet ${wide ? 'wide' : ''} ${size ?? ''}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <header>
          <h2>{title}</h2>
          <span className="sheet-actions">
            {actions}
            <button type="button" className="quiet" onClick={requestClose}>
              關閉
            </button>
          </span>
        </header>
        {children}
      </div>
    </div>
  );
}

/** A「?」that shows its text in a small bubble; closes on a second click, Esc or a click elsewhere. */
export function HelpTip({ label = '說明', children }: { label?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    // Capture, so Esc closes the bubble without also closing the sheet.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopImmediatePropagation();
      setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey, true);
    };
  }, [open]);
  return (
    <span className="help-tip" ref={ref}>
      <button type="button" className="help-btn" aria-label={label} aria-expanded={open} onClick={() => setOpen(!open)}>
        ?
      </button>
      {open && (
        <span className="help-pop" role="note">
          {children}
        </span>
      )}
    </span>
  );
}

// Online-order terms per broker: fee discount on the 0.1425% rate and the minimum fee per trade.
// 國泰證券: 2.8折, 低消 1 元 for app/web orders (checked 2026-10-11; see DESIGN.md 5.3).
export const BROKERS: { name: string; fee_discount: string; fee_min: string }[] = [{ name: '國泰證券', fee_discount: '0.28', fee_min: '1' }];

// Accounts whose balance is normally negative (money owed), so no warning.
const DEBT_TYPES = ['credit', 'loan'];

/** 新增帳戶 step 1: what kind of account. `inst` = which institutions step 2 offers (none: skip it). */
const NEW_KINDS: {
  key: string;
  label: string;
  hint: string;
  icon: IconName;
  type: string;
  group?: boolean;
  inst?: InstitutionKind;
  suffix: string; // after the institution: 玉山 + 信用卡
  fallback: string; // name when no institution is picked
}[] = [
  { key: 'bank', label: '銀行', hint: '活存、數位帳戶', icon: 'bank', type: 'bank', inst: 'bank', suffix: '', fallback: '銀行' },
  { key: 'cash', label: '現金', hint: '錢包裡的錢', icon: 'cash', type: 'cash', suffix: '', fallback: '現金' },
  { key: 'credit', label: '信用卡', hint: '刷卡的支出記在這裡', icon: 'card', type: 'credit', inst: 'bank', suffix: '信用卡', fallback: '信用卡' },
  { key: 'broker_tw', label: '台股券商', hint: '買賣台股、ETF', icon: 'candles', type: 'broker_tw', inst: 'broker', suffix: '證券', fallback: '證券' },
  { key: 'broker_us', label: '複委託', hint: '美股、港股，可以有多種幣別', icon: 'globe', type: 'broker_us', group: true, inst: 'broker', suffix: '複委託', fallback: '複委託' },
  { key: 'fx', label: '外幣帳戶', hint: '一個帳戶裡有好幾種外幣', icon: 'coin', type: 'bank', group: true, inst: 'bank', suffix: '外幣', fallback: '外幣存款' },
  { key: 'deposit', label: '定存', hint: '年利率、到期日', icon: 'hourglass', type: 'deposit', inst: 'bank', suffix: '定存', fallback: '定存' },
  { key: 'loan', label: '貸款', hint: '房貸、信貸', icon: 'loan', type: 'loan', inst: 'bank', suffix: '貸款', fallback: '房貸' },
];
type NewKind = (typeof NEW_KINDS)[number];

type View =
  | { step: 'list' }
  | { step: 'kind' }
  | { step: 'inst'; kind: NewKind }
  | { step: 'account'; input: AccountInput; kind?: NewKind; inst?: string } // kind: reached through 新增
  | { step: 'group'; input: GroupInput; kind?: NewKind; inst?: string };

const FILTER_KEY = 'ledger.accounts.filter';
const readFilter = () => {
  try {
    return localStorage.getItem(FILTER_KEY) ?? 'all';
  } catch {
    return 'all';
  }
};

export function AccountsPanel({ state, onState, onClose }: { state: State; onState(s: State): void; onClose(): void }) {
  const [view, setView] = useState<View>(state.accounts.length === 0 ? { step: 'kind' } : { step: 'list' });
  const [filter, setFilterState] = useState(readFilter);
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setFilter = (f: string) => {
    setFilterState(f);
    try {
      localStorage.setItem(FILTER_KEY, f);
    } catch {
      // private window: the filter just isn't remembered
    }
  };
  const go = (v: View) => {
    setError(null);
    setView(v);
  };
  const done = (r: { ok: true; state: State } | { ok: false; error: string }) => {
    if (!r.ok) return setError(r.error);
    go({ step: 'list' });
    onState(r.state);
  };

  const takenGroups = state.account_groups.map(g => g.name);
  const start = (kind: NewKind, inst: Institution | null) => {
    const name = uniqueName(inst ? `${inst.name}${kind.suffix}` : kind.fallback, state.accounts, takenGroups);
    if (kind.group) {
      const currencies = kind.type === 'broker_us' ? ['USD', 'HKD'] : ['USD'];
      return go({ step: 'group', input: { name, type: kind.type, currencies, color: '' }, kind, inst: inst?.name });
    }
    const broker = kind.type === 'broker_tw' ? BROKERS.find(b => inst && b.name.startsWith(inst.name)) : undefined;
    const input: AccountInput = { name, type: kind.type, currency: 'TWD', fee_discount: broker?.fee_discount ?? '', fee_min: broker?.fee_min ?? '', color: '' };
    go({ step: 'account', input, kind, inst: inst?.name });
  };

  const editAccount = (a: AccountRow) =>
    go({
      step: 'account',
      input: {
        id: a.id,
        name: a.name,
        type: a.type,
        currency: a.currency,
        fee_discount: a.fee_discount ?? '',
        fee_min: a.fee_min ?? '',
        rate: a.rate ?? '',
        start_date: a.start_date ?? '',
        maturity_date: a.maturity_date ?? '',
        principal: a.principal ?? '',
        term_years: a.term_years ?? '',
        grace_years: a.grace_years ?? '',
        archived: a.archived,
        color: a.color ?? '',
      },
    });

  const help = (
    <HelpTip label="帳戶說明">
      <b>開始記帳</b>
      先建立帳戶，再用「＋ 記一筆 → 其他 → 存入現金」記下每個帳戶現在的餘額（勾「期初」），用「買進」勾「補登」補上手上的持股。
      <b>一行輸入</b>
      用 <code>@名稱</code> 指定帳戶，例如 <code>支出 120 午餐 @現金</code>；多幣別帳戶寫 <code>@外幣存款-USD</code>。
      <b>顏色</b>
      依名稱裡的銀行或券商自動決定，打開帳戶可以改。
      <b>負的餘額</b>
      信用卡和貸款是負的屬於正常（代表欠款）。其他帳戶是負的，代表買進或花掉的錢還沒記到那個帳戶，用「其他 → 存入現金」補上。
    </HelpTip>
  );

  let body: ReactNode;
  if (view.step === 'kind') {
    body = (
      <>
        {state.accounts.length > 0 && <BackLink onClick={() => go({ step: 'list' })}>帳戶清單</BackLink>}
        <p className="step-title">要新增哪一種帳戶？</p>
        <div className="kind-tiles">
          {NEW_KINDS.map(k => (
            <button key={k.key} type="button" className="kind-tile" onClick={() => (k.inst ? go({ step: 'inst', kind: k }) : start(k, null))}>
              <Icon name={k.icon} size={22} />
              <span className="strong">{k.label}</span>
              <span className="sub">{k.hint}</span>
            </button>
          ))}
        </div>
      </>
    );
  } else if (view.step === 'inst') {
    const kind = view.kind;
    body = (
      <>
        <BackLink onClick={() => go({ step: 'kind' })}>選類型</BackLink>
        <p className="step-title">{kind.label}：哪一家？</p>
        <div className="inst-tiles">
          {INSTITUTIONS.filter(i => kind.inst && i.kinds.includes(kind.inst)).map(i => (
            <button key={i.name} type="button" className="inst-tile" style={{ '--acct': i.color } as CSSProperties} onClick={() => start(kind, i)}>
              {i.name}
            </button>
          ))}
          <button type="button" className="inst-tile other" onClick={() => start(kind, null)}>
            其他（自己填）
          </button>
        </div>
      </>
    );
  } else if (view.step === 'account' || view.step === 'group') {
    const v = view;
    const back = v.kind ? () => go(v.kind!.inst ? { step: 'inst', kind: v.kind! } : { step: 'kind' }) : () => go({ step: 'list' });
    body = (
      <>
        <BackLink onClick={back}>{v.kind ? '上一步' : '帳戶清單'}</BackLink>
        {v.kind && <p className="step-title">{[v.kind.label, v.inst].filter(Boolean).join('・')}</p>}
        {v.step === 'account' ? (
          <AccountForm
            key={v.input.id ?? `new-${v.input.name}`}
            initial={v.input}
            types={state.account_types}
            currencies={state.currencies}
            error={error}
            onSave={async a => done(await api.saveAccount(a))}
            onCancel={() => go({ step: 'list' })}
            onDelete={v.input.id != null ? async () => done(await api.deleteAccount(v.input.id!)) : undefined}
          />
        ) : (
          <GroupForm
            key={v.input.old_name ?? `new-${v.input.name}`}
            initial={v.input}
            currencies={state.currencies}
            error={error}
            onSave={async g => done(await api.saveGroup(g))}
            onCancel={() => go({ step: 'list' })}
            onDelete={v.input.old_name ? async () => done(await api.deleteGroup(v.input.old_name!)) : undefined}
          />
        )}
      </>
    );
  } else {
    body = (
      <AccountList
        state={state}
        filter={filter}
        setFilter={setFilter}
        showArchived={showArchived}
        setShowArchived={setShowArchived}
        onAccount={editAccount}
        onGroup={g => go({ step: 'group', input: { name: g.name, old_name: g.name, type: g.type, currencies: g.currencies, color: g.color ?? '' } })}
        onAdd={() => go({ step: 'kind' })}
      />
    );
  }

  return (
    <Sheet title="帳戶" onClose={onClose} size="xwide" actions={help}>
      {body}
    </Sheet>
  );
}

function BackLink({ onClick, children }: { onClick(): void; children: ReactNode }) {
  return (
    <button type="button" className="quiet back" onClick={onClick}>
      ‹ {children}
    </button>
  );
}

function AccountList(props: {
  state: State;
  filter: string;
  setFilter(f: string): void;
  showArchived: boolean;
  setShowArchived(b: boolean): void;
  onAccount(a: AccountRow): void;
  onGroup(g: AccountGroup): void;
  onAdd(): void;
}) {
  const { state, showArchived } = props;
  const singles = state.accounts.filter(a => !a.group_name);
  // One entry per account; a multi-currency account counts once, under its type.
  const entries = [
    ...singles.map(a => ({ type: a.type, archived: a.archived })),
    ...state.account_groups.map(g => ({ type: g.type, archived: g.archived })),
  ];
  const live = entries.filter(e => !e.archived);
  const counts = new Map<string, number>();
  for (const e of live) counts.set(e.type, (counts.get(e.type) ?? 0) + 1);
  const types = Object.keys(state.account_types).filter(t => counts.has(t));
  const filter = props.filter === 'all' || counts.has(props.filter) ? props.filter : 'all';
  const archivedCount = entries.length - live.length;
  const shown = (type: string, archived: boolean) => (filter === 'all' || type === filter) && (showArchived || !archived);
  // Archived ones last, otherwise in the order they were made.
  const rows: { archived: boolean; account?: AccountRow; group?: AccountGroup }[] = [
    ...singles.filter(a => shown(a.type, a.archived)).map(a => ({ archived: a.archived, account: a })),
    ...state.account_groups.filter(g => shown(g.type, g.archived)).map(g => ({ archived: g.archived, group: g })),
  ].sort((x, y) => Number(x.archived) - Number(y.archived));
  const negative = state.accounts.some(a => !a.archived && a.cash_sign < 0 && !DEBT_TYPES.includes(a.type));

  return (
    <>
      <div className="acct-bar">
        <div className="seg acct-filter" role="tablist" aria-label="依類型篩選">
          {['all', ...types].map(t => (
            <button key={t} type="button" role="tab" aria-selected={filter === t} className={filter === t ? 'on' : ''} onClick={() => props.setFilter(t)}>
              {t === 'all' ? '全部' : state.account_types[t]} <span className="num count">{t === 'all' ? live.length : counts.get(t)}</span>
            </button>
          ))}
        </div>
        {archivedCount > 0 && (
          <label className="check small">
            <input type="checkbox" checked={showArchived} onChange={e => props.setShowArchived(e.target.checked)} />
            顯示已封存（{archivedCount}）
          </label>
        )}
      </div>
      {negative && <p className="note warn">有帳戶的現金是負的，按右上角的「?」看怎麼處理。</p>}
      <div className="table acct-t">
        <div className="thead" aria-hidden>
          <span>帳戶</span>
          <span className="hide-sm">類型</span>
          <span className="hide-sm">幣別</span>
          <span>現金餘額</span>
          <span className="hide-sm">持股市值</span>
        </div>
        {rows.map(r =>
          r.account ? (
            <AccountLine key={r.account.id} a={r.account} onClick={() => props.onAccount(r.account!)} />
          ) : (
            <GroupLine key={r.group!.name} g={r.group!} state={state} onClick={() => props.onGroup(r.group!)} />
          ),
        )}
        {rows.length === 0 && <p className="muted empty">沒有帳戶</p>}
      </div>
      <div className="actions end">
        <button type="button" className="primary" onClick={props.onAdd}>
          ＋ 新增帳戶
        </button>
      </div>
    </>
  );
}

function AccountBadge({ name, color, type }: { name: string; color?: string | null; type: string }) {
  return (
    <span className="icon-badge" style={{ color: accountColor({ name, type, color }) }}>
      <Icon name={accountIcon(type)} />
    </span>
  );
}

function AccountLine({ a, onClick }: { a: AccountRow; onClick(): void }) {
  const inst = institutionOf(a.name);
  return (
    <button
      type="button"
      className={`trow acct-row ${a.archived ? 'archived' : ''}`}
      style={{ '--acct': accountColor(a) } as CSSProperties}
      onClick={onClick}
    >
      <span className="cell-ic">
        <AccountBadge name={a.name} color={a.color} type={a.type} />
        <span className="cell">
          <span className="ellipsis">{a.name}</span>
          <span className="sub">
            {inst && inst.name !== a.name ? inst.name : ''}
            <span className="show-sm">
              {inst && inst.name !== a.name ? '・' : ''}
              {a.type_label}
            </span>
            {a.archived ? '　已封存' : ''}
          </span>
        </span>
      </span>
      <span className="cell hide-sm">{a.type_label}</span>
      <span className="cell hide-sm">
        <span className="code">{a.currency}</span>
      </span>
      <span className="cell r">
        <span className={a.cash_sign < 0 && !DEBT_TYPES.includes(a.type) ? 'warn' : ''}>
          <Money className="num" value={a.cash} />
        </span>
      </span>
      <span className="cell r hide-sm">{a.holdings ? <Money className="num" value={a.holdings} /> : <span className="muted">—</span>}</span>
    </button>
  );
}

function GroupLine({ g, state, onClick }: { g: AccountGroup; state: State; onClick(): void }) {
  const parts = state.accounts.filter(a => a.group_name === g.name && !a.archived);
  const color = accountColor({ name: g.name, type: g.type, color: g.color });
  return (
    <div className={`acct-group ${g.archived ? 'archived' : ''}`} style={{ '--acct': color } as CSSProperties}>
      <button type="button" className="trow acct-row" onClick={onClick}>
        <span className="cell-ic">
          <AccountBadge name={g.name} color={g.color} type={g.type} />
          <span className="cell">
            <span className="ellipsis">{g.name}</span>
            <span className="sub">
              {g.currencies.length} 種幣別{g.archived ? '　已封存' : ''}
            </span>
          </span>
        </span>
        <span className="cell hide-sm">{state.account_types[g.type]}</span>
        <span className="cell hide-sm muted">多幣別</span>
        <span className="cell r">
          <span>
            ≈ <Money className="num" value={g.total} />
          </span>
          <span className="sub">台幣合計</span>
        </span>
        <span className="cell r hide-sm" />
      </button>
      {parts.map(a => (
        <div key={a.id} className="trow sub-row">
          <span className="cell">
            <span>
              <span className="code">{a.currency}</span>　{state.currencies[a.currency] ?? ''}
            </span>
          </span>
          <span className="cell hide-sm" />
          <span className="cell hide-sm" />
          <span className="cell r">
            <span className={a.cash_sign < 0 ? 'warn' : ''}>
              <Money className="num" value={a.cash} />
            </span>
            <span className="sub">
              ≈ <Money className="num" value={a.value_twd} />
            </span>
          </span>
          <span className="cell r hide-sm" />
        </div>
      ))}
    </div>
  );
}

/** 自動 (from the name) or one of the swatches. */
function ColorField({ name, type, value, onChange }: { name: string; type: string; value: string; onChange(c: string): void }) {
  const auto = accountColor({ name, type, color: null });
  return (
    <div className="field">
      <span className="field-head">顏色</span>
      <div className="swatches" role="radiogroup" aria-label="顏色">
        <button
          type="button"
          role="radio"
          aria-checked={!value}
          className={`swatch auto ${!value ? 'on' : ''}`}
          style={{ '--sw': auto } as CSSProperties}
          onClick={() => onChange('')}
        >
          自動
        </button>
        {SWATCHES.map(c => (
          <button
            key={c}
            type="button"
            role="radio"
            aria-checked={value === c}
            aria-label={c}
            className={`swatch ${value === c ? 'on' : ''}`}
            style={{ '--sw': c } as CSSProperties}
            onClick={() => onChange(c)}
          />
        ))}
      </div>
    </div>
  );
}

function GroupForm(props: {
  initial: GroupInput;
  currencies: Record<string, string>;
  error: string | null;
  onSave(g: GroupInput): void;
  onCancel(): void;
  onDelete?: () => void;
}) {
  const [g, setG] = useState(props.initial);
  const toggle = (c: string) =>
    setG({ ...g, currencies: g.currencies.includes(c) ? g.currencies.filter(x => x !== c) : [...g.currencies, c] });
  return (
    <form
      className="form acct-form"
      onSubmit={e => {
        e.preventDefault();
        props.onSave(g);
      }}
    >
      <div className="field">
        <span className="field-head">
          <label htmlFor="group-name">名稱</label>
          <HelpTip label="多幣別帳戶說明">
            記帳時選這個帳戶再選幣別；一行輸入寫 <code>@{g.name || '國泰外幣'}-USD</code>。取消勾選有交易的幣別會封存，不會刪掉紀錄。
          </HelpTip>
        </span>
        <input id="group-name" value={g.name} autoFocus onChange={e => setG({ ...g, name: e.target.value })} placeholder="國泰外幣" />
      </div>
      <label>
        類型
        <select value={g.type} onChange={e => setG({ ...g, type: e.target.value })}>
          <option value="bank">銀行外幣存款</option>
          <option value="broker_us">複委託（買美股、港股等）</option>
          <option value="cash">外幣現金</option>
        </select>
      </label>
      <fieldset className="checks">
        <legend>{g.type === 'broker_us' ? '要交易哪些市場的幣別（美股 USD、港股 HKD、日股 JPY…）' : '這個帳戶有哪些外幣'}</legend>
        {Object.entries(props.currencies)
          .filter(([c]) => c !== 'TWD')
          .map(([c, name]) => (
            <label key={c} className="check">
              <input type="checkbox" checked={g.currencies.includes(c)} onChange={() => toggle(c)} />
              {name} {c}
            </label>
          ))}
      </fieldset>
      <ColorField name={g.name} type={g.type} value={g.color ?? ''} onChange={color => setG({ ...g, color })} />
      {props.error && <p className="message bad">{props.error}</p>}
      <div className="actions">
        <button type="submit" className="primary">
          {props.initial.old_name ? '儲存帳戶' : '建立帳戶'}
        </button>
        <button type="button" className="quiet" onClick={props.onCancel}>
          取消
        </button>
        {props.onDelete && (
          <button type="button" className="quiet danger" onClick={props.onDelete}>
            刪除帳戶
          </button>
        )}
      </div>
    </form>
  );
}

function uniqueName(base: string, accounts: AccountRow[], groups: string[] = []): string {
  let name = base;
  for (let i = 2; accounts.some(a => a.name === name) || groups.includes(name); i++) name = `${base}${i}`;
  return name;
}

function AccountForm(props: {
  initial: AccountInput;
  types: Record<string, string>;
  currencies: Record<string, string>;
  error: string | null;
  onSave(a: AccountInput): void;
  onCancel(): void;
  onDelete?: () => void;
}) {
  const [a, setA] = useState(props.initial);
  const set = (patch: Partial<AccountInput>) => setA({ ...a, ...patch });
  const isBroker = a.type === 'broker_tw';
  return (
    <form
      className="form acct-form"
      onSubmit={e => {
        e.preventDefault();
        props.onSave(a);
      }}
    >
      <label>
        名稱
        <input value={a.name} autoFocus onChange={e => set({ name: e.target.value })} />
      </label>
      <div className="field-row two">
        <label>
          類型
          <select
            value={a.type}
            onChange={e => set({ type: e.target.value, currency: e.target.value === 'broker_us' ? 'USD' : a.type === 'broker_us' ? 'TWD' : a.currency })}
          >
            {Object.entries(props.types).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <div className="field">
          <span className="field-head">
            <label htmlFor="acct-ccy">幣別</label>
            <HelpTip label="幣別說明">一個帳戶一種幣別；同一個外幣綜合存款裡有好幾種外幣，用「外幣帳戶（多幣別）」建立。</HelpTip>
          </span>
          <select id="acct-ccy" value={a.currency ?? 'TWD'} onChange={e => set({ currency: e.target.value })}>
            {Object.entries(props.currencies).map(([code, name]) => (
              <option key={code} value={code}>
                {name}（{code}）
              </option>
            ))}
            {a.currency && !(a.currency in props.currencies) && <option value={a.currency}>{a.currency}</option>}
          </select>
        </div>
      </div>
      {isBroker && (
        <>
          <label>
            券商
            <select
              value={BROKERS.find(b => b.fee_discount === a.fee_discount && b.fee_min === a.fee_min)?.name ?? ''}
              onChange={e => {
                const b = BROKERS.find(x => x.name === e.target.value);
                if (b) set({ fee_discount: b.fee_discount, fee_min: b.fee_min, name: a.name && a.id != null ? a.name : b.name });
              }}
            >
              {BROKERS.map(b => (
                <option key={b.name} value={b.name}>
                  {b.name}（{Number(b.fee_discount) * 10} 折，最低 {b.fee_min} 元）
                </option>
              ))}
              <option value="">其他（自己填）</option>
            </select>
          </label>
          <div className="field-row two">
            <label>
              手續費折扣
              <input value={a.fee_discount ?? ''} placeholder="用預設" inputMode="decimal" onChange={e => set({ fee_discount: e.target.value })} />
            </label>
            <label>
              最低手續費
              <input value={a.fee_min ?? ''} placeholder="用預設" inputMode="decimal" onChange={e => set({ fee_min: e.target.value })} />
            </label>
          </div>
        </>
      )}
      {a.type === 'deposit' && (
        <>
          <div className="field">
            <span className="field-head">
              <label htmlFor="acct-rate">年利率（%）</label>
              <HelpTip label="定存怎麼記">
                本金用轉帳記：<code>轉 500000 @銀行 @{a.name || '定存'}</code>
              </HelpTip>
            </span>
            <input id="acct-rate" value={a.rate ?? ''} inputMode="decimal" placeholder="1.7" onChange={e => set({ rate: e.target.value })} />
          </div>
          <div className="field-row two">
            <label>
              起存日
              <input type="date" value={a.start_date ?? ''} onChange={e => set({ start_date: e.target.value })} />
            </label>
            <label>
              到期日
              <input type="date" value={a.maturity_date ?? ''} onChange={e => set({ maturity_date: e.target.value })} />
            </label>
          </div>
        </>
      )}
      {a.type === 'loan' && (
        <>
          <div className="field-row two">
            <div className="field">
              <span className="field-head">
                <label htmlFor="acct-principal">貸款金額</label>
                <HelpTip label="貸款怎麼記">
                  撥款用轉帳記：<code>轉 8000000 @{a.name || '房貸'} @銀行</code>（已經還了一段時間的，填目前剩餘本金）。每月還款：
                  <code>還 @{a.name || '房貸'} @銀行</code>
                </HelpTip>
              </span>
              <input id="acct-principal" value={a.principal ?? ''} inputMode="decimal" placeholder="8000000" onChange={e => set({ principal: e.target.value })} />
            </div>
            <label>
              年利率（%）
              <input value={a.rate ?? ''} inputMode="decimal" placeholder="2.1" onChange={e => set({ rate: e.target.value })} />
            </label>
            <label>
              年期
              <input value={a.term_years ?? ''} inputMode="decimal" placeholder="30" onChange={e => set({ term_years: e.target.value })} />
            </label>
            <label>
              寬限期（年）
              <input value={a.grace_years ?? ''} inputMode="decimal" placeholder="沒有就留空" onChange={e => set({ grace_years: e.target.value })} />
            </label>
          </div>
          <label>
            撥款日
            <input type="date" value={a.start_date ?? ''} onChange={e => set({ start_date: e.target.value })} />
          </label>
        </>
      )}
      <ColorField name={a.name} type={a.type} value={a.color ?? ''} onChange={color => set({ color })} />
      {a.id != null && (
        <label className="check">
          <input type="checkbox" checked={!!a.archived} onChange={e => set({ archived: e.target.checked })} />
          封存（不再出現在預設帳戶裡）
        </label>
      )}
      {props.error && <p className="message bad">{props.error}</p>}
      <div className="actions">
        <button type="submit" className="primary">
          {a.id != null ? '儲存帳戶' : '建立帳戶'}
        </button>
        <button type="button" className="quiet" onClick={props.onCancel}>
          取消
        </button>
        {props.onDelete && (
          <button type="button" className="quiet danger" onClick={props.onDelete}>
            刪除帳戶
          </button>
        )}
      </div>
    </form>
  );
}

export function SettingsPanel({ state, onState, onClose }: { state: State; onState(s: State): void; onClose(): void }) {
  const [s, setS] = useState<Settings>(state.settings);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);

  async function save(patch: Partial<Settings>) {
    const next = { ...s, ...patch };
    setS(next);
    const r = await api.saveSettings(patch);
    if (!r.ok) return setMsg({ text: r.error, bad: true });
    setMsg({ text: '已儲存' });
    onState(r.state);
  }

  async function run(fn: () => Promise<{ ok: true; path: string } | { ok: false; error: string }>, done: string) {
    const r = await fn();
    setMsg(r.ok ? { text: `${done}：${r.path}` } : { text: r.error, bad: true });
  }

  return (
    <Sheet title="設定" onClose={onClose}>
      <form className="form" onSubmit={e => e.preventDefault()}>
        <label>
          台股手續費折扣
          <input
            defaultValue={s.fee_discount}
            inputMode="decimal"
            onBlur={e => e.target.value !== s.fee_discount && save({ fee_discount: e.target.value })}
          />
          <small className="muted">0.6 代表六折；帳戶可以各自設定</small>
        </label>
        <label>
          最低手續費
          <input defaultValue={s.fee_min} inputMode="decimal" onBlur={e => e.target.value !== s.fee_min && save({ fee_min: e.target.value })} />
        </label>
        <label>
          漲跌顏色
          <select value={s.up_color} onChange={e => save({ up_color: e.target.value as Settings['up_color'] })}>
            <option value="red">漲紅跌綠</option>
            <option value="green">漲綠跌紅</option>
          </select>
        </label>
        <label>
          外幣換算台幣用
          <select
            value={s.fx_source}
            onChange={async e => {
              await save({ fx_source: e.target.value as Settings['fx_source'] });
              await api.refresh(); // fetch the chosen rates now
            }}
          >
            <option value="cathay">國泰世華 即期買進（跟國泰 App 一樣）</option>
            <option value="market">市場中間價（Yahoo）</option>
          </select>
          <small className="muted">銀行買進價是現在把外幣換回台幣實際拿到的價格；換外幣時沒填匯率，會用國泰的即期賣出價</small>
        </label>
        <label className="check">
          <input type="checkbox" checked={s.privacy === '1'} onChange={e => save({ privacy: e.target.checked ? '1' : '0' })} />
          隱藏金額（⌘⇧H）
        </label>
      </form>
      <div className="actions">
        <button type="button" className="chip" onClick={() => run(api.exportCsv, '已匯出')}>
          匯出交易 CSV
        </button>
        <button type="button" className="chip" onClick={() => run(api.backup, '已備份')}>
          備份資料庫
        </button>
      </div>
      <AdviceThresholds
        onSaved={async ok => {
          setMsg(ok === true ? { text: '已儲存' } : { text: ok, bad: true });
          const r = await api.state();
          if (r.ok) onState(r.state); // the 健檢 card refetches on a new state
        }}
      />
      {msg && <p className={`message ${msg.bad ? 'bad' : 'muted'}`}>{msg.text}</p>}
    </Sheet>
  );
}

const THRESHOLDS: [string, string, string][] = [
  ['fund_min_months', '緊急預備金至少', '個月支出'],
  ['fund_max_months', '現金超過就提醒', '個月支出'],
  ['drift_pct', '配置偏離超過', '個百分點'],
  ['stock_note_pct', '單一個股佔投資超過（提醒）', '%'],
  ['stock_warn_pct', '單一個股佔投資超過（警示）', '%'],
  ['loan_note_pct', '貸款月付佔收入超過（提醒）', '%'],
  ['loan_warn_pct', '貸款月付佔收入超過（警示）', '%'],
  ['savings_min_pct', '儲蓄率低於', '%'],
  ['deposit_days', '定存到期前', '天提醒'],
  ['near_years', '幾年內要用的錢該放現金', '年'],
];

/** 健檢 thresholds, collapsed by default. */
function AdviceThresholds({ onSaved }: { onSaved(ok: true | string): void }) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string> | null>(null);
  useEffect(() => {
    if (!open || values) return;
    void api.advice().then(r => r.ok && setValues(r.advice.thresholds));
  }, [open, values]);

  async function save(k: string, v: string) {
    if (!values || values[k] === v) return;
    const next = { ...values, [k]: v };
    const r = await api.saveAdviceThresholds(next);
    if (r.ok) setValues(r.advice.thresholds);
    onSaved(r.ok ? true : r.error);
  }

  return (
    <div className="inline-form">
      <button type="button" className="quiet" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} 健檢門檻
      </button>
      {open && values && (
        <form className="form thresholds" onSubmit={e => e.preventDefault()}>
          {THRESHOLDS.map(([k, label, unit]) => (
            <label key={k}>
              {label}
              <span className="unit-input">
                <input className="num" inputMode="decimal" defaultValue={values[k]} onBlur={e => void save(k, e.target.value)} />
                <span className="muted">{unit}</span>
              </span>
            </label>
          ))}
        </form>
      )}
    </div>
  );
}
