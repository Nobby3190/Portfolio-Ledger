import { Fragment, useEffect, useState } from 'react';
import { api } from '../api';
import { categoryIcon, IconBadge } from '../lib/icons';
import { Money, RollingMoney, signClass, Trend } from '../lib/privacy';
import type { State, YearChange, YearReport } from '../types';
import { PairBars } from './Charts';

/** 收支 in 年 mode: the year against last year, its twelve months, categories and net worth. */
export function YearView({ state, onPickMonth }: { state: State; onPickMonth(month: string): void }) {
  const [year, setYear] = useState<number | null>(null);
  const [report, setReport] = useState<YearReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openCat, setOpenCat] = useState<number | null>(null); // the row showing its 子類別

  useEffect(() => {
    let live = true;
    void api.year(year).then(r => {
      if (!live) return;
      if (r.ok) {
        setReport(r.year);
        setError(null);
      } else setError(r.error);
    });
    return () => {
      live = false;
    };
  }, [year, state]);

  if (error) return <p className="message bad span-12">{error}</p>;
  if (!report) return null;
  const y = report;
  const last = y.year - 1;
  return (
    <>
      <nav className="month-tabs span-12" aria-label="選年份">
        {y.tabs.map(t => (
          <button
            key={t.year}
            type="button"
            className={t.year === y.year ? 'on' : ''}
            aria-current={t.year === y.year ? 'true' : undefined}
            onClick={() => setYear(t.year === Number(state.today.slice(0, 4)) ? null : t.year)}
          >
            <span>{t.label} 年</span>
            <Money className="num tiny" value={t.expense} />
          </button>
        ))}
      </nav>

      <section className="card hero span-7" aria-label="全年支出">
        <div className="hero-top">
          <div>
            <p className="label">{y.is_current ? `今年到 ${y.elapsed} 月花了` : `${y.label}花了`}</p>
            <h1 className="hero-num">
              <span className="ccy">NT$</span>
              <RollingMoney id="year-expense" value={y.expense} />
            </h1>
          </div>
        </div>
        <p className="budget-text">
          平均每月 <Money value={y.per_month} />
          <Change label={y.compare_label} c={y.vs_last.expense} />
        </p>
        <dl className="metrics">
          <div>
            <dt>收入</dt>
            <dd>
              <Money className="num" value={y.income} />
              {y.vs_last.income && (
                <span className="delta trend-line">
                  <Trend sign={y.vs_last.income.sign} />
                  <Money value={y.vs_last.income.delta} />
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt>結餘</dt>
            <dd>
              <Trend sign={y.net_sign} />
              <Money className="num" value={y.net} />
            </dd>
          </div>
          <div>
            <dt>儲蓄率</dt>
            <dd className="num">
              {y.savings_rate ?? '—'}
              {y.vs_last.savings_rate && <span className="delta">去年同期 {y.vs_last.savings_rate}</span>}
            </dd>
          </div>
        </dl>
      </section>

      {y.has_data && (
        <section className="card stretch span-5" aria-labelledby="ytrend-h">
          <header className="card-head">
            <h2 id="ytrend-h">每個月</h2>
            <span className="aside">點一個月看明細</span>
          </header>
          <PairBars
            names={['收入', '支出']}
            onPick={i => !y.trend[i].future && onPickMonth(y.trend[i].month)}
            ariaLabel={`${y.label}每個月的收入與支出`}
            height={196}
            data={y.trend.map(t => ({ label: String(Number(t.month.slice(5))), a: t.income, b: t.expense, a_s: t.income_s, b_s: t.expense_s }))}
          />
        </section>
      )}

      {!y.has_data && (
        <section className="card first span-12">
          <header className="card-head">
            <h2>{y.label}沒有收支紀錄</h2>
          </header>
        </section>
      )}

      {y.categories.length > 0 && (
        <section className="card span-7" aria-labelledby="ycat-h">
          <header className="card-head">
            <h2 id="ycat-h">支出分類</h2>
            <span className="aside">月平均以 {y.elapsed} 個月計</span>
          </header>
          <div className="table ycat-t">
            <div className="thead" aria-hidden>
              <span>分類</span>
              <span>全年</span>
              <span className="hide-sm">月平均</span>
              <span className="hide-sm">預算 × 12</span>
              <span className="hide-sm">{y.is_current ? '比去年同期' : `比 ${last} 年`}</span>
            </div>
            {y.categories
              .flatMap(p => [{ c: p, sub: false }, ...(openCat === p.id ? (p.children ?? []).map(k => ({ c: k, sub: true })) : [])])
              .map(({ c, sub }) => {
                const kids = c.children?.length ?? 0;
                const toggle = () => kids > 0 && setOpenCat(openCat === c.id ? null : c.id);
                return (
              // tabIndex: the row's details card (below) opens on keyboard focus too; a row with 子類別 opens them on click/Enter
              <div
                key={`${sub ? 'sub-' : ''}${c.id}${c.own ? '-own' : ''}`}
                className={`trow has-tip ${sub ? 'kid-row' : ''} ${kids ? 'has-kids' : ''}`}
                tabIndex={0}
                aria-label={c.name}
                aria-expanded={kids ? openCat === c.id : undefined}
                onClick={toggle}
                onKeyDown={e => e.key === 'Enter' && toggle()}
              >
                {/* The columns can squeeze the name to just its icon, so pointing at a row shows everything
                    about it in one card (使用者回饋 2026-10-16). Money stays masked in privacy mode. */}
                <span className="tip row-tip" role="tooltip">
                  <span className="row-tip-name">
                    <IconBadge name={categoryIcon(c.name, 'expense')} tone="expense" category={c.name} />
                    {c.name}
                    <span className="muted">佔 {Math.round(c.share * 100)}%</span>
                  </span>
                  <span className="row-tip-grid">
                    <span className="muted">全年</span>
                    <Money className="num" value={c.amount} />
                    <span className="muted">月平均</span>
                    <Money className="num" value={c.per_month} />
                    {c.budget_ratio != null && (
                      <>
                        <span className="muted">預算 × 12</span>
                        <span className={`num ${c.budget_ratio > 1 ? 'warn' : ''}`}>用了 {Math.round(c.budget_ratio * 100)}%</span>
                      </>
                    )}
                    <span className="muted">{y.is_current ? '比去年同期' : `比 ${last} 年`}</span>
                    {c.delta && c.delta_sign !== 0 ? (
                      <span className="trend-line">
                        <Trend sign={c.delta_sign} />
                        <Money className="num" value={c.delta} />
                      </span>
                    ) : (
                      <span>{c.last ? '持平' : '—'}</span>
                    )}
                    {c.children?.map(k => (
                      <Fragment key={`${k.id}${k.own ? '-own' : ''}`}>
                        <span className="muted row-tip-kid">{k.name}</span>
                        <Money className="num" value={k.amount} />
                      </Fragment>
                    ))}
                  </span>
                </span>
                <span className="cell-ic">
                  <IconBadge name={categoryIcon(c.name, 'expense')} tone="expense" category={c.name} />
                  <span className="cell">
                    <span className="ellipsis">{c.name}</span>
                    <span className="sub">
                      佔 {Math.round(c.share * 100)}%{kids > 0 && ` · ${kids} 個子類別 ${openCat === c.id ? '▾' : '▸'}`}
                    </span>
                  </span>
                </span>
                <span className="cell r">
                  <Money className="num" value={c.amount} />
                </span>
                <span className="cell r hide-sm">
                  <Money className="num small" value={c.per_month} />
                </span>
                <span className="bar-cell hide-sm">
                  {c.budget_ratio != null ? (
                    <>
                      <span className={`meter ${c.budget_ratio > 1 ? 'over' : c.budget_ratio >= 0.8 ? 'near' : ''}`} aria-hidden>
                        <span style={{ width: `${Math.min(c.budget_ratio, 1) * 100}%` }} />
                      </span>
                      <span className={`num small ${c.budget_ratio > 1 ? 'warn' : ''}`}>{Math.round(c.budget_ratio * 100)}%</span>
                    </>
                  ) : (
                    <span className="muted small">—</span>
                  )}
                </span>
                <span className="cell r hide-sm">
                  {c.delta && c.delta_sign !== 0 ? (
                    <span className="trend-line">
                      <Trend sign={c.delta_sign} />
                      <Money className="num small" value={c.delta} />
                    </span>
                  ) : (
                    <span className="muted small">{c.last ? '持平' : '—'}</span>
                  )}
                </span>
              </div>
                );
              })}
          </div>
        </section>
      )}

      <div className="stack span-5">
        {y.worth && (
          <section className="card" aria-labelledby="yworth-h">
            <header className="card-head">
              <h2 id="yworth-h">淨值</h2>
            </header>
            <div className="table income-t">
              <div className="trow">
                <span>年初</span>
                <span className="cell r">
                  <Money className="num" value={y.worth.start} />
                </span>
              </div>
              <div className="trow">
                <span>{y.is_current ? '現在' : '年底'}</span>
                <span className="cell r">
                  <Money className="num" value={y.worth.end} />
                </span>
              </div>
              <div className="trow">
                <span>變化</span>
                <span className={`cell r ${signClass(y.worth.sign)}`}>
                  <span className="trend-line">
                    <Trend sign={y.worth.sign} />
                    <Money className="num" value={y.worth.change} />
                  </span>
                  {y.worth.pct && <span className="sub">{y.worth.pct}</span>}
                </span>
              </div>
            </div>
            <p className="note">含投資漲跌，不只是存下來的錢。</p>
          </section>
        )}
        {y.income_categories.length > 0 && (
          <section className="card" aria-labelledby="yinc-h">
            <header className="card-head">
              <h2 id="yinc-h">收入</h2>
            </header>
            <div className="table income-t">
              {y.income_categories.map(c => (
                <div key={c.name} className="trow">
                  <span className="cell-ic">
                    <IconBadge name={categoryIcon(c.name, 'income')} tone="income" category={c.name} />
                    <span className="cell">
                      <span className="ellipsis">{c.name}</span>
                      <span className="sub">佔 {Math.round(c.share * 100)}%</span>
                    </span>
                  </span>
                  <span className="cell r">
                    <Money className="num" value={c.amount} />
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </>
  );
}

function Change({ c, label }: { c: YearChange | null; label?: string }) {
  if (!c) return null;
  return (
    <span className="sub muted">
      {label ? `　${label} ` : ' '}
      <span className="trend-line">
        <Trend sign={c.sign} />
        <Money value={c.delta} />
        {c.pct && `（${c.pct}）`}
      </span>
    </span>
  );
}
