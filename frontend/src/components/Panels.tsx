import { type ReactNode, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { Money } from '../lib/privacy';
import type { AccountInput, AccountRow, GroupInput, Settings, State } from '../types';

export function Sheet({ title, onClose, children, wide = false }: { title: string; onClose(): void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    // Leave focus alone if a field inside (autoFocus) already took it.
    if (!ref.current?.contains(document.activeElement)) ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      prev?.focus?.();
    };
  }, [onClose]);
  return (
    <div className="scrim" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className={`sheet ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <header>
          <h2>{title}</h2>
          <button type="button" className="quiet" onClick={onClose}>
            關閉
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}

// Online-order terms per broker: fee discount on the 0.1425% rate and the minimum fee per trade.
// 國泰證券: 2.8折, 低消 1 元 for app/web orders (checked 2026-10-11; see DESIGN.md 5.3).
export const BROKERS: { name: string; fee_discount: string; fee_min: string }[] = [{ name: '國泰證券', fee_discount: '0.28', fee_min: '1' }];

// Accounts whose balance is normally negative (money owed), so no warning.
const DEBT_TYPES = ['credit', 'loan'];

const PRESETS: AccountInput[] = [
  { name: '國泰證券', type: 'broker_tw', currency: 'TWD', fee_discount: '0.28', fee_min: '1' },
  { name: '銀行', type: 'bank', currency: 'TWD' },
  { name: '信用卡', type: 'credit', currency: 'TWD' },
  { name: '定存', type: 'deposit', currency: 'TWD' },
  { name: '房貸', type: 'loan', currency: 'TWD' },
];

export function AccountsPanel({ state, onState, onClose }: { state: State; onState(s: State): void; onClose(): void }) {
  const [editing, setEditing] = useState<AccountInput | null>(state.accounts.length === 0 ? { ...PRESETS[0] } : null);
  const [group, setGroup] = useState<GroupInput | null>(null);
  const [error, setError] = useState<string | null>(null);

  const done = (r: { ok: true; state: State } | { ok: false; error: string }) => {
    if (!r.ok) return setError(r.error);
    setError(null);
    setEditing(null);
    setGroup(null);
    onState(r.state);
  };

  const singles = state.accounts.filter(a => !a.group_name);
  const editAccount = (a: AccountRow) => {
    setGroup(null);
    setEditing({
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
    });
  };

  return (
    <Sheet title="帳戶" onClose={onClose}>
      {state.accounts.length === 0 && (
        <p className="lead">先建立一個帳戶，之後用「＋ 記一筆 → 其他 → 存入現金」記下目前的餘額，用「買進」補上手上的持股。</p>
      )}
      <div className="table acct-t">
        {singles.map(a => (
          <button key={a.id} type="button" className={`trow ${a.archived ? 'archived' : ''}`} onClick={() => editAccount(a)}>
            <span className="cell">
              <span className="ellipsis">{a.name}</span>
              <span className="sub">
                {a.type_label}　{a.currency}
                {a.archived ? '　已封存' : ''}
              </span>
            </span>
            <span className="cell r">
              <span className={a.cash_sign < 0 && !DEBT_TYPES.includes(a.type) ? 'warn' : ''}>
                <Money className="num" value={a.cash} />
                {a.currency !== 'TWD' && <span className="ccy-tag">{a.currency}</span>}
              </span>
              {a.holdings && (
                <span className="sub">
                  持股 <Money className="num" value={a.holdings} />
                </span>
              )}
            </span>
          </button>
        ))}
        {state.account_groups.map(g => {
          const parts = state.accounts.filter(a => a.group_name === g.name && !a.archived);
          return (
            <div key={g.name} className={`acct-group ${g.archived ? 'archived' : ''}`}>
              <button
                type="button"
                className="trow"
                onClick={() => {
                  setEditing(null);
                  setGroup({ name: g.name, old_name: g.name, type: g.type, currencies: g.currencies });
                }}
              >
                <span className="cell">
                  <span className="ellipsis">{g.name}</span>
                  <span className="sub">
                    {state.account_types[g.type]}　{g.currencies.length} 種幣別{g.archived ? '　已封存' : ''}
                  </span>
                </span>
                <span className="cell r">
                  <span>
                    ≈ <Money className="num" value={g.total} />
                  </span>
                  <span className="sub">台幣合計</span>
                </span>
              </button>
              {parts.map(a => (
                <div key={a.id} className="trow sub-row">
                  <span className="cell">
                    <span>
                      <span className="code">{a.currency}</span>　{state.currencies[a.currency] ?? ''}
                    </span>
                  </span>
                  <span className="cell r">
                    <span className={a.cash_sign < 0 ? 'warn' : ''}>
                      <Money className="num" value={a.cash} />
                    </span>
                    <span className="sub">
                      ≈ <Money className="num" value={a.value_twd} />
                    </span>
                  </span>
                </div>
              ))}
            </div>
          );
        })}
      </div>
      {state.accounts.some(a => a.cash_sign < 0 && !DEBT_TYPES.includes(a.type)) && (
        <p className="note">有帳戶現金是負的，代表買進或花掉的錢還沒記到那個帳戶；用「其他 → 存入現金」補上。信用卡和貸款是負的屬於正常（代表欠款）。</p>
      )}

      {editing ? (
        <AccountForm
          key={editing.id ?? 'new'}
          initial={editing}
          types={state.account_types}
          currencies={state.currencies}
          error={error}
          onSave={async a => done(await api.saveAccount(a))}
          onCancel={() => {
            setEditing(null);
            setError(null);
          }}
          onDelete={editing.id != null ? async () => done(await api.deleteAccount(editing.id!)) : undefined}
        />
      ) : group ? (
        <GroupForm
          key={group.old_name ?? 'new'}
          initial={group}
          currencies={state.currencies}
          error={error}
          onSave={async g => done(await api.saveGroup(g))}
          onCancel={() => {
            setGroup(null);
            setError(null);
          }}
          onDelete={group.old_name ? async () => done(await api.deleteGroup(group.old_name!)) : undefined}
        />
      ) : (
        <div className="presets">
          <span className="muted">新增</span>
          {PRESETS.map(p => (
            <button key={p.name} type="button" className="chip" onClick={() => setEditing({ ...p, name: uniqueName(p.name, state.accounts) })}>
              {p.type === 'broker_tw' ? `台股券商（${p.name}）` : state.account_types[p.type]}
            </button>
          ))}
          <button
            type="button"
            className="chip"
            onClick={() => setGroup({ name: uniqueName('國泰複委託', state.accounts, state.account_groups.map(g => g.name)), type: 'broker_us', currencies: ['USD', 'HKD'] })}
          >
            複委託（美股、港股…）
          </button>
          <button
            type="button"
            className="chip"
            onClick={() => setGroup({ name: uniqueName('外幣存款', state.accounts, state.account_groups.map(g => g.name)), type: 'bank', currencies: ['USD'] })}
          >
            外幣帳戶（多幣別）
          </button>
        </div>
      )}
    </Sheet>
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
      className="form"
      onSubmit={e => {
        e.preventDefault();
        props.onSave(g);
      }}
    >
      <label>
        名稱
        <input value={g.name} autoFocus onChange={e => setG({ ...g, name: e.target.value })} placeholder="國泰外幣" />
      </label>
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
      <small className="muted">
        記帳時選這個帳戶再選幣別；一行輸入寫 <code>@{g.name || '國泰外幣'}-USD</code>。取消勾選有交易的幣別會封存，不會刪掉紀錄。
      </small>
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
      className="form"
      onSubmit={e => {
        e.preventDefault();
        props.onSave(a);
      }}
    >
      <label>
        名稱
        <input value={a.name} autoFocus onChange={e => set({ name: e.target.value })} />
      </label>
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
      <label>
        幣別
        <select value={a.currency ?? 'TWD'} onChange={e => set({ currency: e.target.value })}>
          {Object.entries(props.currencies).map(([code, name]) => (
            <option key={code} value={code}>
              {name}（{code}）
            </option>
          ))}
          {a.currency && !(a.currency in props.currencies) && <option value={a.currency}>{a.currency}</option>}
        </select>
        <small className="muted">一個帳戶一種幣別；同一個外幣綜合存款裡有好幾種外幣，就每種各建一個帳戶</small>
      </label>
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
          <label>
            手續費折扣
            <input value={a.fee_discount ?? ''} placeholder="用預設" inputMode="decimal" onChange={e => set({ fee_discount: e.target.value })} />
          </label>
          <label>
            最低手續費
            <input value={a.fee_min ?? ''} placeholder="用預設" inputMode="decimal" onChange={e => set({ fee_min: e.target.value })} />
          </label>
        </>
      )}
      {a.type === 'deposit' && (
        <>
          <label>
            年利率（%）
            <input value={a.rate ?? ''} inputMode="decimal" placeholder="1.7" onChange={e => set({ rate: e.target.value })} />
          </label>
          <label>
            起存日
            <input type="date" value={a.start_date ?? ''} onChange={e => set({ start_date: e.target.value })} />
          </label>
          <label>
            到期日
            <input type="date" value={a.maturity_date ?? ''} onChange={e => set({ maturity_date: e.target.value })} />
          </label>
          <small className="muted">本金用轉帳記：轉 500000 @銀行 @{a.name || '定存'}</small>
        </>
      )}
      {a.type === 'loan' && (
        <>
          <label>
            貸款金額
            <input value={a.principal ?? ''} inputMode="decimal" placeholder="8000000" onChange={e => set({ principal: e.target.value })} />
          </label>
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
          <label>
            撥款日
            <input type="date" value={a.start_date ?? ''} onChange={e => set({ start_date: e.target.value })} />
          </label>
          <small className="muted">
            撥款用轉帳記：轉 8000000 @{a.name || '房貸'} @銀行（已經還了一段時間的，填目前剩餘本金）。每月還款：還 @{a.name || '房貸'} @銀行
          </small>
        </>
      )}
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
