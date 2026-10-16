import { type ReactNode, useContext, useEffect, useState } from 'react';
import { api } from '../api';
import { categoryIcon, categoryTone, IconBadge, toneOf, txIcon } from '../lib/icons';
import { Money, PrivacyContext, RollingMoney, Trend } from '../lib/privacy';
import type { MonthReport, RecurringRule, State } from '../types';
import { TxList } from './Activity';
import { PairBars } from './Charts';
import { YearView } from './YearView';

const FLOW_KINDS = ['income', 'expense', 'transfer', 'repay'];

export function MoneyView({ state, onEdit, onPanel }: { state: State; onEdit(id: number): void; onPanel(p: 'search' | 'recurring'): void }) {
  const [mode, setMode] = useState<'month' | 'year'>('month');
  const [month, setMonth] = useState<string | null>(null);
  const bar = (
    <div className="money-bar span-12">
      <div className="seg" role="radiogroup" aria-label="看一個月或一整年">
        {(['month', 'year'] as const).map(k => (
          <button key={k} type="button" role="radio" aria-checked={mode === k} className={mode === k ? 'on' : ''} onClick={() => setMode(k)}>
            {k === 'month' ? '月' : '年'}
          </button>
        ))}
      </div>
      <span className="money-actions">
        <button type="button" className="quiet" onClick={() => onPanel('recurring')}>
          週期性
        </button>
        <button type="button" className="quiet" onClick={() => onPanel('search')} title="⌘F">
          搜尋
        </button>
      </span>
    </div>
  );
  if (mode === 'year')
    return (
      <div className="grid">
        {bar}
        <YearView
          state={state}
          onPickMonth={m => {
            setMonth(m === state.today.slice(0, 7) ? null : m);
            setMode('month');
          }}
        />
      </div>
    );
  return <MonthView state={state} onEdit={onEdit} onPanel={onPanel} month={month} setMonth={setMonth} bar={bar} />;
}

function MonthView({
  state,
  onEdit,
  onPanel,
  month,
  setMonth,
  bar,
}: {
  state: State;
  onEdit(id: number): void;
  onPanel(p: 'search' | 'recurring'): void;
  month: string | null;
  setMonth(m: string | null): void;
  bar: ReactNode;
}) {
  const hidden = useContext(PrivacyContext);
  const [report, setReport] = useState<MonthReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Reload when the month changes or anything was recorded (state is replaced on every save).
  useEffect(() => {
    let live = true;
    void api.month(month).then(r => {
      if (!live) return;
      if (r.ok) {
        setReport(r.month);
        setError(null);
      } else setError(r.error);
    });
    return () => {
      live = false;
    };
  }, [month, state]);

  if (error) return <p className="message bad">{error}</p>;
  if (!report) return null;
  const m = report;
  const rows = state.transactions.filter(t => t.date.startsWith(m.month) && FLOW_KINDS.includes(t.kind));
  // A month still to come lists every category, so budgets can be set ahead.
  const cats = m.is_future ? m.categories : m.categories.filter(c => c.spent !== '0' || c.budget);
  const unused = m.categories.filter(c => c.spent === '0' && !c.budget).map(c => c.name);

  async function saveTotal(v: string) {
    const r = await api.setTotalBudget(v, m.month);
    if (r.ok) setReport(r.month);
    else setError(r.error);
  }
  async function saveCategory(id: number, v: string) {
    const r = await api.setBudget(id, v, m.month);
    if (r.ok) setReport(r.month);
    else setError(r.error);
  }

  const ratio = m.budget_ratio ?? 0;
  const thisMonth = state.today.slice(0, 7);
  const tabTop = Math.max(1, ...m.tabs.map(t => t.expense));
  return (
    <div className="grid">
      {bar}
      <nav className="month-tabs span-12" aria-label="選月份">
        <button type="button" className="quiet" onClick={() => setMonth(m.prev)} aria-label="更早">
          ‹
        </button>
        {m.tabs.map(t => (
          <button
            key={t.month}
            type="button"
            className={`${t.month === m.month ? 'on' : ''} ${t.future ? 'future' : ''}`}
            aria-current={t.month === m.month ? 'true' : undefined}
            onClick={() => setMonth(t.month === thisMonth ? null : t.month)}
          >
            {/* each month's spending as a small bar on one scale (大膽版) */}
            <span className="tab-bar" aria-hidden>
              <span style={{ height: `${t.future ? 0 : Math.max((t.expense / tabTop) * 100, 4)}%` }} />
            </span>
            <span>{t.month.slice(0, 4) !== thisMonth.slice(0, 4) ? `${t.month.slice(0, 4)} 年 ` : ''}{t.label}</span>
            {t.future ? <span className="tiny">還沒到</span> : <Money className="num tiny" value={t.expense_s} />}
          </button>
        ))}
        {m.next && (
          <button type="button" className="quiet" onClick={() => setMonth(m.next === thisMonth ? null : m.next)} aria-label="更晚">
            ›
          </button>
        )}
      </nav>
      <section className="card hero span-7" aria-label="本月支出">
        <div className="hero-top">
          <div>
            <p className="label">{m.is_future ? `${m.label}的預算` : m.is_current ? '這個月花了' : `${m.label}花了`}</p>
            <h1 className="hero-num">
              <span className="ccy">NT$</span>
              <RollingMoney id="month-expense" value={m.is_future ? (m.budget ?? '—') : m.expense} />
            </h1>
          </div>
          {m.budget && !m.is_future && <BudgetRing ratio={ratio} state={m.over ? 'over' : ratio >= 0.8 ? 'near' : ''} />}
        </div>
        {/* The number's underline: how much of the budget is gone. */}
        <div className={`budget-line ${m.over ? 'over' : ratio >= 0.8 ? 'near' : ''}`} aria-hidden>
          <span style={{ width: `${Math.min(ratio, 1) * 100}%` }} />
        </div>
        <p className="budget-text">
          {m.is_future ? (
            <span className="muted">{m.budget ? '還沒到這個月。' : '還沒設定每月預算。'}預算是每個月共用的，改了每個月都會一起變。</span>
          ) : m.budget ? (
            m.over ? (
              <span className="warn">
                預算 <Money value={m.budget} />，已超出 <Money value={m.budget_left?.replace('−', '')} />
              </span>
            ) : (
              <>
                預算 <Money value={m.budget} />，還剩 <Money className="strong" value={m.budget_left} />
                {m.days_left != null && m.per_day && (
                  <span className="muted">
                    （還有 {m.days_left} 天，每天約 <Money value={m.per_day} />）
                  </span>
                )}
              </>
            )
          ) : (
            <span className="muted">還沒設定每月預算</span>
          )}
          <InlineAmount label={m.budget_total_setting ? '修改' : '設定預算'} value={m.budget_total_setting} onSave={saveTotal} />
          {!m.is_current && (
            <button type="button" className="quiet" onClick={() => setMonth(null)}>
              回到本月
            </button>
          )}
        </p>
        <dl className="metrics">
          <div>
            <dt>收入</dt>
            <dd>
              <Money className="num" value={m.income} />
            </dd>
          </div>
          <div>
            <dt>結餘</dt>
            <dd>
              <Trend sign={m.net_sign} />
              <Money className="num" value={m.net} />
            </dd>
          </div>
          <div>
            <dt>儲蓄率</dt>
            <dd className="num">{m.savings_rate ?? '—'}</dd>
          </div>
        </dl>

      </section>

      {m.trend.some(t => t.income || t.expense) && (
        <section className="card stretch span-5" aria-labelledby="trend-h">
          <header className="card-head">
            <h2 id="trend-h">近 6 個月</h2>
          </header>
          <PairBars
            names={['收入', '支出']}
            selected={m.trend.findIndex(t => t.month === m.month)}
            onPick={i => {
              const picked = m.trend[i].month;
              setMonth(picked === thisMonth ? null : picked);
            }}
            ariaLabel="近 6 個月收入與支出"
            height={196}
            data={m.trend.map(t => ({ label: t.label, a: t.income, b: t.expense, a_s: t.income_s, b_s: t.expense_s }))}
          />
        </section>
      )}

      {!m.has_data && (
        <section className="card first span-12">
          <header className="card-head">
            <h2>{m.is_future ? `${m.label}還沒到` : m.is_current ? '這個月還沒有收支' : '這個月沒有收支紀錄'}</h2>
          </header>
          {m.is_future ? (
            <p>可以先在上面設定每月總預算，或在「支出分類」給各分類設定預算。到了這個月再記帳。</p>
          ) : (
          <p>
            在上方輸入 <code>支出 120 午餐</code>、<code>收入 60000 薪資</code>；信用卡刷卡記在信用卡帳戶：<code>支出 1200 購物 @信用卡</code>。
          </p>
          )}
        </section>
      )}

      {cats.length > 0 && (
        <section className="card span-7" aria-labelledby="cat-h">
          <header className="card-head">
            <h2 id="cat-h">支出分類</h2>
            <span className="aside">點「設定」可以給分類每月預算</span>
          </header>
          {/* one tile per category, in the category's colour (大膽版); amber still means near or over budget */}
          <div className="cat-tiles">
            {cats.map(c => {
              const r = c.budget_ratio;
              const st = r == null ? '' : r > 1 ? 'over' : r >= 0.8 ? 'near' : '';
              return (
                <div key={c.id} className={`cat-tile ${st}`} style={{ '--t': categoryTone(c.name, 'expense') } as React.CSSProperties}>
                  <span className="cat-tile-top">
                    <IconBadge name={categoryIcon(c.name, 'expense')} tone="expense" />
                    {!m.is_future && <span className="num muted small">{Math.round(c.share * 100)}%</span>}
                  </span>
                  <span className="cat-tile-name ellipsis">{c.name}</span>
                  <Money className="num cat-tile-amt" value={c.spent} />
                  <span className={`meter ${st}`} aria-hidden>
                    <span style={{ width: `${r == null ? 0 : Math.min(r, 1) * 100}%` }} />
                  </span>
                  <span className="cat-tile-foot">
                    <span className="cat-tile-budget">
                      預算 <InlineAmount label={c.budget ? (hidden ? '••••' : c.budget) : '設定'} value={c.budget_raw} onSave={v => saveCategory(c.id, v)} />
                    </span>
                    {r != null && <span className={`num ${r > 1 ? 'warn' : ''}`}>{Math.round(r * 100)}%</span>}
                  </span>
                  {!m.is_future && c.delta && c.delta_sign !== 0 && (
                    <span className="cat-tile-delta trend-line">
                      比上月 <Trend sign={c.delta_sign} />
                      <Money className="num" value={c.delta} />
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          {unused.length > 0 && (
            <p className="note">
              其他分類：{unused.join('、')}。輸入分類名稱的一部分就會對到（「餐」→ 餐飲），新名稱會自動建立分類。
            </p>
          )}
        </section>
      )}

      <div className="stack span-5">
      {m.income_categories.length > 0 && (
        <section className="card" aria-labelledby="inc-h">
          <header className="card-head">
            <h2 id="inc-h">收入</h2>
          </header>
          <div className="table income-t">
            {m.income_categories.map(c => (
              <div key={c.name} className="trow">
                <span className="cell-ic">
                  <IconBadge name={categoryIcon(c.name, 'income')} tone="income" />
                  <span className="ellipsis">{c.name}</span>
                </span>
                <span className="cell r">
                  <Money className="num" value={c.amount} />
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
      {m.is_current && <Upcoming state={state} onOpen={() => onPanel('recurring')} />}
      </div>

      {rows.length > 0 && (
        <section className="card span-12" aria-labelledby="mrows-h">
          <header className="card-head">
            <h2 id="mrows-h">{m.is_current ? '這個月的紀錄' : `${m.label}的紀錄`}</h2>
            <span className="aside">{rows.length} 筆，點一筆可以修改</span>
          </header>
          <TxList rows={rows} onEdit={onEdit} months={false} />
        </section>
      )}
    </div>
  );
}

/** A quiet button that turns into an amount field; Enter or leaving the field saves, Esc cancels. */
export function InlineAmount({ label, value, onSave }: { label: string; value: string; onSave(v: string): void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(value);
  if (!editing)
    return (
      <button
        type="button"
        className="quiet num"
        onClick={() => {
          setText(value);
          setEditing(true);
        }}
      >
        {label}
      </button>
    );
  const done = (save: boolean) => {
    setEditing(false);
    if (save && text !== value) onSave(text);
  };
  return (
    <input
      className="inline-input num"
      autoFocus
      inputMode="decimal"
      value={text}
      placeholder="留空＝不設定"
      aria-label={label}
      onChange={e => setText(e.target.value)}
      onBlur={() => done(true)}
      onKeyDown={e => {
        if (e.key === 'Enter') done(true);
        if (e.key === 'Escape') {
          e.stopPropagation();
          done(false);
        }
      }}
    />
  );
}

/** 接下來 30 天: what the 週期性 rules will post soon, under 收入 on the current month. */
function Upcoming({ state, onOpen }: { state: State; onOpen(): void }) {
  const [rules, setRules] = useState<RecurringRule[]>([]);
  useEffect(() => {
    let live = true;
    void api.recurring().then(r => live && r.ok && setRules(r.rules));
    return () => {
      live = false;
    };
  }, [state]);
  const until = new Date(`${state.today}T00:00:00`);
  until.setDate(until.getDate() + 30);
  const pad = (n: number) => String(n).padStart(2, '0');
  const end = `${until.getFullYear()}-${pad(until.getMonth() + 1)}-${pad(until.getDate())}`; // local date, not UTC
  const soon = rules
    .filter(r => r.active && r.next_date && r.next_date <= end)
    .sort((a, b) => a.next_date!.localeCompare(b.next_date!));
  if (soon.length === 0) return null;
  return (
    <section className="card" aria-labelledby="soon-h">
      <header className="card-head">
        <h2 id="soon-h">接下來 30 天</h2>
        <button type="button" className="quiet" onClick={onOpen}>
          週期性
        </button>
      </header>
      <div className="table soon-t">
        {soon.slice(0, 6).map(r => (
          <button key={r.id} type="button" className="trow" onClick={onOpen}>
            <span className="cal" aria-label={r.next_date!}>
              <small>{Number(r.next_date!.slice(5, 7))} 月</small>
              <b className="num">{Number(r.next_date!.slice(8))}</b>
            </span>
            <span className="cell-ic">
              <IconBadge name={txIcon(r.kind, r.category, r.line)} tone={toneOf(r.kind)} />
              <span className="ellipsis">{r.title}</span>
            </span>
            <span className="cell r">{r.amount ? <Money className="num" value={r.amount} /> : <span className="muted small">月付</span>}</span>
          </button>
        ))}
      </div>
      {soon.length > 6 && <p className="note">還有 {soon.length - 6} 筆</p>}
    </section>
  );
}

/** The share of the month's budget that is gone, as a 270° ring beside the big number. */
function BudgetRing({ ratio, state }: { ratio: number; state: string }) {
  const r = 34;
  const c = 2 * Math.PI * r;
  const arc = c * 0.75;
  return (
    <span className={`budget-ring ${state}`} aria-hidden>
      <svg viewBox="0 0 84 84" width="84" height="84">
        <circle className="track" cx="42" cy="42" r={r} strokeDasharray={`${arc} ${c}`} transform="rotate(135 42 42)" />
        <circle className="fill" cx="42" cy="42" r={r} strokeDasharray={`${arc * Math.min(ratio, 1)} ${c}`} transform="rotate(135 42 42)" />
      </svg>
      <span className="num">{Math.round(ratio * 100)}%</span>
    </span>
  );
}
