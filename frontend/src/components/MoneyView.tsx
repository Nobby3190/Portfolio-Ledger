import { type ReactNode, useContext, useEffect, useState } from 'react';
import { api } from '../api';
import { Money, PrivacyContext } from '../lib/privacy';
import type { MonthReport, State } from '../types';
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
  return <MonthView state={state} onEdit={onEdit} month={month} setMonth={setMonth} bar={bar} />;
}

function MonthView({
  state,
  onEdit,
  month,
  setMonth,
  bar,
}: {
  state: State;
  onEdit(id: number): void;
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
              <Money value={m.is_future ? (m.budget ?? '—') : m.expense} />
            </h1>
          </div>
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
          <div className="table cat-t">
            <div className="thead" aria-hidden>
              <span>分類</span>
              <span>本月</span>
              <span>預算</span>
              <span className="hide-sm">比上月</span>
            </div>
            {cats.map(c => {
              const r = c.budget_ratio;
              return (
                <div key={c.id} className="trow">
                  <span className="cell">
                    <span className="ellipsis">{c.name}</span>
                    {!m.is_future && <span className="sub">佔本月 {Math.round(c.share * 100)}%</span>}
                  </span>
                  <span className="cell r">
                    <Money className="num" value={c.spent} />
                  </span>
                  <span className="bar-cell">
                    {r != null && (
                      <>
                        <span className={`meter ${r > 1 ? 'over' : r >= 0.8 ? 'near' : ''}`} aria-hidden>
                          <span style={{ width: `${Math.min(r, 1) * 100}%` }} />
                        </span>
                        <span className={`num small ${r > 1 ? 'warn' : ''}`}>{Math.round(r * 100)}%</span>
                      </>
                    )}
                    <InlineAmount label={c.budget ? (hidden ? '••••' : c.budget) : '設定'} value={c.budget_raw} onSave={v => saveCategory(c.id, v)} />
                  </span>
                  <span className="cell r hide-sm">
                    {!m.is_future && c.delta && c.delta_sign !== 0 ? <Money className="num small" value={c.delta} /> : <span className="muted small">—</span>}
                  </span>
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
                <span>{c.name}</span>
                <span className="cell r">
                  <Money className="num" value={c.amount} />
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

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
