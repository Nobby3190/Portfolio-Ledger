import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { IconBadge, toneOf, txIcon } from '../lib/icons';
import { Money } from '../lib/privacy';
import type { Preview, RecurringFreq, RecurringInput, RecurringRule, State, TxRow } from '../types';
import { TxList } from './Activity';
import { Sheet } from './Panels';

// ── 搜尋與篩選 ─────────────────────────────────────────────────────────

const FLOW = ['income', 'expense', 'transfer', 'repay'];
type Period = 'month' | 'year' | 'all' | 'custom';
interface Filters {
  q: string;
  kind: '' | 'expense' | 'income' | 'transfer';
  category: string;
  account: string;
  period: Period;
  from: string;
  to: string;
  min: string;
  max: string;
}
const NO_FILTERS: Filters = { q: '', kind: '', category: '', account: '', period: 'all', from: '', to: '', min: '', max: '' };
// Kept while the app runs, so opening a result and coming back finds the same search.
let lastFilters: Filters = NO_FILTERS;
const PAGE = 100;

/** Totals are whole NT$ in the same style as the Python side (1,234). */
const twd = (n: number) => Math.round(n).toLocaleString('en-US');

export function SearchPanel({ state, onEdit, onClose }: { state: State; onEdit(id: number): void; onClose(): void }) {
  const [f, setF] = useState<Filters>(lastFilters);
  const [limit, setLimit] = useState(PAGE);
  const set = (patch: Partial<Filters>) => {
    setF(prev => (lastFilters = { ...prev, ...patch }));
    setLimit(PAGE);
  };

  const rows = useMemo(() => filter(state.transactions, f, state.today), [state.transactions, f, state.today]);
  const spent = rows.filter(t => t.kind === 'expense').reduce((s, t) => s + t.value, 0);
  const earned = rows.filter(t => t.kind === 'income').reduce((s, t) => s + t.value, 0);
  const cats = [...new Set(state.categories.filter(c => !f.kind || c.kind === f.kind).map(c => c.name))];
  const accounts = state.accounts; // archived ones too: their history is searchable

  return (
    <Sheet title="搜尋紀錄" onClose={onClose} wide>
      <div className="search">
        <input
          className="search-q field-input"
          autoFocus
          value={f.q}
          placeholder="備註、分類或帳戶，例如：全聯"
          aria-label="關鍵字"
          onChange={e => set({ q: e.target.value })}
        />
        <div className="seg" role="radiogroup" aria-label="類型">
          {([['', '全部'], ['expense', '支出'], ['income', '收入'], ['transfer', '轉帳與還款']] as const).map(([k, label]) => (
            <button key={k} type="button" role="radio" aria-checked={f.kind === k} className={f.kind === k ? 'on' : ''} onClick={() => set({ kind: k, category: '' })}>
              {label}
            </button>
          ))}
        </div>
        <div className="search-grid">
          <label className="field">
            <span className="field-label">期間</span>
            <select value={f.period} onChange={e => set({ period: e.target.value as Period })}>
              <option value="month">本月</option>
              <option value="year">今年</option>
              <option value="all">全部</option>
              <option value="custom">自訂</option>
            </select>
          </label>
          {f.period === 'custom' && (
            <>
              <label className="field">
                <span className="field-label">從</span>
                <input type="date" value={f.from} onChange={e => set({ from: e.target.value })} />
              </label>
              <label className="field">
                <span className="field-label">到</span>
                <input type="date" value={f.to} onChange={e => set({ to: e.target.value })} />
              </label>
            </>
          )}
          {f.kind !== 'transfer' && (
            <label className="field">
              <span className="field-label">分類</span>
              <select value={f.category} onChange={e => set({ category: e.target.value })}>
                <option value="">全部</option>
                {cats.map(c => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
          )}
          <label className="field">
            <span className="field-label">帳戶</span>
            <select value={f.account} onChange={e => set({ account: e.target.value })}>
              <option value="">全部</option>
              {accounts.map(a => (
                <option key={a.id}>{a.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">金額（台幣）</span>
            <span className="range">
              <input className="num" inputMode="decimal" value={f.min} placeholder="最少" aria-label="金額下限" onChange={e => set({ min: e.target.value })} />
              <span className="muted">–</span>
              <input className="num" inputMode="decimal" value={f.max} placeholder="最多" aria-label="金額上限" onChange={e => set({ max: e.target.value })} />
            </span>
          </label>
        </div>
        <p className="search-sum" aria-live="polite">
          <span>{rows.length} 筆</span>
          {spent > 0 && (
            <span>
              支出 <Money className="num strong" value={twd(spent)} />
            </span>
          )}
          {earned > 0 && (
            <span>
              收入 <Money className="num strong" value={twd(earned)} />
            </span>
          )}
          {JSON.stringify(f) !== JSON.stringify(NO_FILTERS) && (
            <button type="button" className="quiet" onClick={() => set(NO_FILTERS)}>
              清除條件
            </button>
          )}
        </p>
        {rows.length > 0 ? (
          <div className="search-list">
            <TxList rows={rows.slice(0, limit)} onEdit={onEdit} />
            {rows.length > limit && (
              <button type="button" className="quiet toggle" onClick={() => setLimit(limit + PAGE)}>
                顯示更多（還有 {rows.length - limit} 筆）
              </button>
            )}
          </div>
        ) : (
          <p className="muted">沒有符合的紀錄</p>
        )}
      </div>
    </Sheet>
  );
}

function filter(all: TxRow[], f: Filters, today: string): TxRow[] {
  const q = f.q.trim().toLowerCase();
  const min = f.min.trim() ? Number(f.min.replace(/,/g, '')) : null;
  const max = f.max.trim() ? Number(f.max.replace(/,/g, '')) : null;
  const [from, to] =
    f.period === 'month' ? [today.slice(0, 7), today.slice(0, 7) + '~'] : f.period === 'year' ? [today.slice(0, 4), today.slice(0, 4) + '~'] : f.period === 'custom' ? [f.from, f.to || '~'] : ['', '~'];
  return all.filter(t => {
    if (!FLOW.includes(t.kind)) return false;
    if (f.kind && (f.kind === 'transfer' ? t.kind !== 'transfer' && t.kind !== 'repay' : t.kind !== f.kind)) return false;
    if (t.date < from || t.date > to) return false;
    if (f.category && t.category !== f.category) return false;
    if (f.account && t.account !== f.account && t.to_account !== f.account) return false;
    if (min != null && !Number.isNaN(min) && t.value < min) return false;
    if (max != null && !Number.isNaN(max) && t.value > max) return false;
    if (q && ![t.note, t.category, t.account, t.to_account, t.label].some(x => x?.toLowerCase().includes(q))) return false;
    return true;
  });
}

// ── 週期性收支 ─────────────────────────────────────────────────────────

const FREQS: [RecurringFreq, string][] = [
  ['monthly', '每月'],
  ['weekly', '每週'],
  ['yearly', '每年'],
];
const WEEKDAYS = '日一二三四五六';
const EXAMPLES = ['支出 15000 居住 # 房租', '收入 60000 薪資', '支出 390 娛樂 @信用卡 # Netflix', '還 @房貸', '定額 0050 10000'];

/** 11/05 this year, 2027/04/10 otherwise. */
const shortDate = (d: string, today: string) => (d.slice(0, 4) === today.slice(0, 4) ? d.slice(5) : d).replaceAll('-', '/');

/** When a rule falls, in words: 每月 5 日, 每週三, 每年 3/5. */
export function when(freq: RecurringFreq, start: string): string {
  const d = new Date(`${start}T00:00:00`);
  if (freq === 'weekly') return `每週${WEEKDAYS[d.getDay()]}`;
  if (freq === 'yearly') return `每年 ${d.getMonth() + 1}/${d.getDate()}`;
  return `每月 ${d.getDate()} 日${d.getDate() > 28 ? '（小月記在月底）' : ''}`;
}

// Filter groups for the panel: [key, label, rule kinds].
const REC_GROUPS: [string, string, string[]][] = [
  ['', '全部', []],
  ['expense', '支出', ['expense']],
  ['income', '收入', ['income']],
  ['move', '轉帳與還款', ['transfer', 'repay']],
  ['dca', '定期定額', ['dca']],
];

/** "約 15,300" for the monthly totals line. */
const roughly = (n: number) => Math.round(n).toLocaleString('en-US');

export function RecurringPanel({ state, onState, onClose, onToast }: { state: State; onState(s: State): void; onClose(): void; onToast(m: string): void }) {
  const [rules, setRules] = useState<RecurringRule[] | null>(null);
  const [editing, setEditing] = useState<RecurringInput | null>(null);
  const [group, setGroup] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.recurring().then(r => (r.ok ? setRules(r.rules) : setError(r.error)));
  }, [state]);

  const open = (r: RecurringRule) =>
    setEditing({ id: r.id, line: r.line, freq: r.freq, start_date: r.start_date, end_date: r.end_date ?? '', active: r.active });
  const back = () => {
    setEditing(null);
    setError(null);
  };

  async function save(data: RecurringInput) {
    const r = await api.saveRecurring(data);
    if (!r.ok) return setError(r.error);
    back();
    setRules(r.rules);
    onState(r.state);
    onToast(r.posted ? `已儲存，記入了 ${r.posted} 筆` : '已儲存');
  }

  async function remove(id: number) {
    const r = await api.deleteRecurring(id);
    if (!r.ok) return setError(r.error);
    back();
    setRules(r.rules);
    onState(r.state);
  }

  // Editing replaces the list, so the form is never far down the sheet.
  if (editing) {
    return (
      <Sheet title={editing.id != null ? '修改週期性收支' : '新增週期性收支'} onClose={onClose} wide>
        <button type="button" className="quiet back" onClick={back}>
          ‹ 回到清單
        </button>
        <RecurringForm
          key={editing.id ?? 'new'}
          initial={editing}
          today={state.today}
          error={error}
          onSave={save}
          onCancel={back}
          onDelete={editing.id != null ? () => remove(editing.id!) : undefined}
        />
      </Sheet>
    );
  }

  const all = rules ?? [];
  const groups = REC_GROUPS.filter(([k, , kinds]) => k === '' || all.some(r => kinds.includes(r.kind)));
  const kinds = REC_GROUPS.find(([k]) => k === group)?.[2] ?? [];
  const shown = group ? all.filter(r => kinds.includes(r.kind)) : all;
  const sum = (ks: string[]) => shown.filter(r => ks.includes(r.kind)).reduce((t, r) => t + (r.monthly ?? 0), 0);
  const totals = (
    [
      ['每月固定支出', sum(['expense', 'repay'])],
      ['固定收入', sum(['income'])],
      ['定期定額', sum(['dca'])],
    ] as const
  ).filter(([, v]) => v > 0);

  return (
    <Sheet title="週期性收支" onClose={onClose} wide>
      <p className="lead">房租、薪水、訂閱、貸款、定期定額這類固定的收支，到日子會自動記一筆（定期定額用當天收盤價算股數）（app 沒開的日子，下次打開時補上）。金額不一樣的那個月，到紀錄裡點一下修改就好。</p>
      {all.length > 0 && (
        <>
          {groups.length > 2 && (
            <div className="seg rec-filter" role="radiogroup" aria-label="類型">
              {groups.map(([k, label, ks]) => (
                <button key={k} type="button" role="radio" aria-checked={group === k} className={group === k ? 'on' : ''} onClick={() => setGroup(k)}>
                  {label}
                  <span className="count">{k ? all.filter(r => ks.includes(r.kind)).length : all.length}</span>
                </button>
              ))}
            </div>
          )}
          {totals.length > 0 && (
            <p className="rec-totals">
              {totals.map(([label, v]) => (
                <span key={label}>
                  {label} 約 <Money className="num strong" value={roughly(v)} />
                </span>
              ))}
              <span className="muted small">每週、每年的換算成每月；暫停的不算</span>
            </p>
          )}
          <div className="table rec-t">
            <div className="thead" aria-hidden>
              <span>名稱</span>
              <span className="hide-sm">下次</span>
              <span>金額</span>
            </div>
            {shown.map(r => (
              <button key={r.id} type="button" className={`trow ${r.active ? '' : 'paused'}`} onClick={() => open(r)}>
                <span className="cell-ic">
                  <IconBadge name={txIcon(r.kind, r.category, r.line)} tone={toneOf(r.kind)} category={r.category} />
                  <span className="cell">
                    <span className="ellipsis">
                      {r.title}
                      {!r.active && <span className="rec-tag">暫停中</span>}
                      {r.error && <span className="rec-tag warn">記不進去</span>}
                    </span>
                    <span className={`sub ${r.error ? 'warn' : ''}`}>
                      {r.error
                        ? r.error
                        : [r.category, `${when(r.freq, r.start_date)}${r.end_date ? `，到 ${r.end_date}` : ''}`].filter(Boolean).join('・')}
                    </span>
                  </span>
                </span>
                <span className="cell r hide-sm">
                  <span className="small">{!r.active ? '—' : r.next_date ? shortDate(r.next_date, state.today) : '已結束'}</span>
                </span>
                <span className="cell r">{r.amount === '帳單金額' ? <span className="muted small">帳單金額</span> : r.amount ? <Money className="num" value={r.amount} /> : <span className="muted small">月付</span>}</span>
              </button>
            ))}
          </div>
        </>
      )}
      {rules && rules.length === 0 && <p className="muted">還沒有週期性收支。也可以在「記一筆」勾選「每月重複」。</p>}
      <div className="actions">
        <button type="button" className="primary" onClick={() => setEditing({ line: '', freq: 'monthly', start_date: state.today, end_date: '', active: true })}>
          ＋ 新增週期性收支
        </button>
        {error && <p className="message bad">{error}</p>}
      </div>
    </Sheet>
  );
}

function RecurringForm(props: {
  initial: RecurringInput;
  today: string;
  error: string | null;
  onSave(r: RecurringInput): void;
  onCancel(): void;
  onDelete?: () => void;
}) {
  const [r, setR] = useState(props.initial);
  const [preview, setPreview] = useState<Preview>({ status: 'empty' });
  const [backfill, setBackfill] = useState(0);
  const set = (patch: Partial<RecurringInput>) => setR(prev => ({ ...prev, ...patch }));

  useEffect(() => {
    let live = true;
    const t = setTimeout(async () => {
      const [p, b] = await Promise.all([api.preview(r.line, null), api.recurringBackfill(r)]);
      if (!live) return;
      setPreview(p.ok ? p.preview : { status: 'error', message: p.error });
      setBackfill(b.ok ? b.count : 0);
    }, 160);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [r]);

  return (
    <form
      className="form"
      onSubmit={e => {
        e.preventDefault();
        props.onSave(r);
      }}
    >
      <label>
        一行內容
        <input value={r.line} autoFocus spellCheck={false} placeholder="支出 15000 居住 @台新 # 房租" onChange={e => set({ line: e.target.value })} />
        <small className="muted">和「記一筆」的一行輸入一樣，不寫日期；# 後面的備註會當作名稱</small>
      </label>
      {!r.line.trim() && (
        <div className="chips">
          {EXAMPLES.map(x => (
            <button key={x} type="button" className="chip ghost" onClick={() => set({ line: x })}>
              {x}
            </button>
          ))}
        </div>
      )}
      <div className={`composer-preview ${preview.status}`} aria-live="polite">
        {preview.status === 'ready' ? (
          <>
            <span className="pv-main">
              <strong>{preview.title}</strong>
              <span className="muted">{preview.parts.join('，')}</span>
            </span>
            {preview.total && <Money className="num pv-total" value={preview.total} />}
          </>
        ) : preview.status === 'error' || preview.status === 'incomplete' ? (
          <span className="warn">{preview.message}</span>
        ) : (
          <span className="muted">打好之後這裡會顯示每次要記的內容</span>
        )}
      </div>
      <div className="seg" role="radiogroup" aria-label="頻率">
        {FREQS.map(([k, label]) => (
          <button key={k} type="button" role="radio" aria-checked={r.freq === k} className={r.freq === k ? 'on' : ''} onClick={() => set({ freq: k })}>
            {label}
          </button>
        ))}
      </div>
      <div className="form-row">
        <label>
          起始日
          <input type="date" value={r.start_date} onChange={e => set({ start_date: e.target.value || props.today })} />
          <small className="muted">{when(r.freq, r.start_date || props.today)}</small>
        </label>
        <label>
          結束日
          <input type="date" value={r.end_date} onChange={e => set({ end_date: e.target.value })} />
          <small className="muted">空白＝一直重複</small>
        </label>
      </div>
      {r.id != null && (
        <label className="check">
          <input type="checkbox" checked={!r.active} onChange={e => set({ active: !e.target.checked })} />
          暫停（恢復時不補記暫停期間）
        </label>
      )}
      {backfill > 0 && <p className="note">存檔後會記入 {backfill} 筆（從起始日到今天）。</p>}
      {props.error && <p className="message bad">{props.error}</p>}
      <div className="actions">
        <button type="submit" className="primary">
          {r.id != null ? '儲存' : '建立'}
        </button>
        <button type="button" className="quiet" onClick={props.onCancel}>
          取消
        </button>
        {props.onDelete && (
          <button type="button" className="quiet danger" onClick={props.onDelete}>
            刪除規則
          </button>
        )}
      </div>
      {props.onDelete && <small className="muted">刪除規則不會刪掉已經記入的紀錄。</small>}
    </form>
  );
}
