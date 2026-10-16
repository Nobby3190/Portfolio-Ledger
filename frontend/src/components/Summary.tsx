import { useState } from 'react';
import { Money, RollingMoney, signClass, Trend } from '../lib/privacy';
import type { State } from '../types';
import { LineChart } from './Charts';

export function NetWorthCard({ state, className = '' }: { state: State; className?: string }) {
  const invested = state.holdings.length > 0 || state.closed.length > 0;
  const h = state.history;
  return (
    <section className={`card hero ${className}`} aria-label="總資產">
      <p className="label">總資產</p>
      <h1 className="hero-num">
        <span className="ccy">NT$</span>
        <RollingMoney id="total" value={state.total} />
      </h1>
      {/* The investment figures (day change, total return) live on the 持股 card, once (2026-10-13);
          this card shows how net worth itself moved. */}
      <NetWorthChanges state={state} />
      {!invested && h.length < 2 && state.allocation_groups.groups.length > 0 && (
        <dl className="metrics">
          {state.allocation_groups.groups.map(g => (
            <div key={g.key}>
              <dt>{g.label}</dt>
              <dd>
                <Money className="num" value={g.value} />
              </dd>
            </div>
          ))}
          {state.allocation_groups.debt_total && (
            <div>
              <dt>負債</dt>
              <dd>
                <Money className="num" value={state.allocation_groups.debt_total} />
              </dd>
            </div>
          )}
        </dl>
      )}
      {h.length < 2 && <p className="note hero-note">淨值走勢從第二天開始畫，每天自動記一次</p>}
      {h.length >= 2 && (
        <div className="hero-chart">
          <LineChart
            ariaLabel="淨值走勢"
            height={200}
            labels={h.map(p => p.date.slice(5).replace('-', '/'))}
            series={[{ name: '淨值', values: h.map(p => Number(p.total)), style: 'main' }]}
            fit
            area
          />
        </div>
      )}
      <AllocRibbon state={state} />
    </section>
  );
}

/** The allocation as one thick band along the bottom of the total (大膽版); the 資產配置 card keeps the rows.
 *  The slate shades are close, so pointing at a segment or its legend entry lifts it, dims the rest and
 *  shows its name, share and amount (2026-10-16). Segments are focusable for the keyboard too. */
function AllocRibbon({ state }: { state: State }) {
  const { groups } = state.allocation_groups;
  const [on, setOn] = useState<string | null>(null);
  if (groups.length === 0) return null;
  const items = groups.flatMap(g => g.items.map((i, n) => ({ ...i, key: `${g.key}-${i.label}`, c: swatch(g.key, n), group: g.label })));
  const first = items[0]?.key;
  const last = items[items.length - 1]?.key;
  const hover = (key: string) => ({
    onMouseEnter: () => setOn(key),
    onMouseLeave: () => setOn(k => (k === key ? null : k)),
    onFocus: () => setOn(key),
    onBlur: () => setOn(k => (k === key ? null : k)),
  });
  return (
    <div className={`ribbon ${on ? 'pointing' : ''}`}>
      <div className="ribbon-bar" role="list" aria-label="資產配置">
        {groups.map(g => (
          <span key={g.key} className="ribbon-group" style={{ flexGrow: Math.max(g.ratio, 0.03) }}>
            {g.items.map((i, n) => {
              const key = `${g.key}-${i.label}`;
              return (
                <span
                  key={key}
                  role="listitem"
                  tabIndex={0}
                  aria-label={`${g.label}・${i.label} ${pct(i.ratio)}`}
                  className={`ribbon-seg ${on === key ? 'on' : ''}`}
                  style={{ flexGrow: i.ratio / (g.ratio || 1), background: swatch(g.key, n) }}
                  {...hover(key)}
                >
                  {on === key && (
                    <span className={`tip ribbon-tip ${key === first ? 'at-start' : key === last ? 'at-end' : ''}`} role="tooltip">
                      <span className="ribbon-tip-name">
                        <i style={{ background: swatch(g.key, n) }} aria-hidden />
                        {i.label}
                        <span className="muted">{g.label}</span>
                      </span>
                      <span className="ribbon-tip-val">
                        <b className="num">{pct(i.ratio)}</b>
                        <Money className="num" value={i.value} />
                      </span>
                    </span>
                  )}
                </span>
              );
            })}
          </span>
        ))}
      </div>
      <ul className="ribbon-legend">
        {items.map(i => (
          <li key={i.key} className={on === i.key ? 'on' : ''} style={{ '--c': i.c } as React.CSSProperties} {...hover(i.key)}>
            <i aria-hidden />
            {i.label} <b className="num">{pct(i.ratio)}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 持股 tile beside the total: market value, the last trading day and unrealized (moved off the 持股 card).
 *  Without holdings it shows the cash group instead, so the column is never empty. */
export function HoldingsTile({ state }: { state: State }) {
  if (state.holdings.length === 0) {
    const cash = state.allocation_groups.groups.find(g => g.key === 'cash');
    if (!cash) return null;
    return (
      <section className="tile tile-slate" aria-label="現金與存款">
        <p className="tile-label">現金與存款</p>
        <p className="tile-num">
          <Money className="num" value={cash.value} />
        </p>
        <p className="tile-sub">佔總資產 {pct(cash.ratio)}</p>
      </section>
    );
  }
  return (
    <section className="tile tile-indigo" aria-label="持股">
      <p className="tile-label">持股市值</p>
      <p className="tile-num">
        <RollingMoney id="holdings" value={state.holdings_value} />
      </p>
      <p className="tile-sub">
        <span>
          最近交易日{' '}
          <span className={`tile-pill ${signClass(state.day_sign)}`}>
            <Trend sign={state.day_sign} />
            {state.day_change_pct ?? <Money value={state.day_change} />}
          </span>
        </span>
        <span>
          未實現{' '}
          <span className={`tile-pill ${signClass(state.holdings_unrealized_sign)}`}>
            <Trend sign={state.holdings_unrealized_sign} />
            <Money className="num" value={state.holdings_unrealized} />
          </span>
        </span>
      </p>
    </section>
  );
}

const pct = (r: number) => (r > 0 && r < 0.005 ? '<1%' : `${Math.round(r * 100)}%`);

/** Item colour: investments take the deep hues, cash-like items the light ones (by rank within the group). */
const swatch = (group: string, i: number) => `var(--${group === 'invest' ? 'inv' : 'csh'}-${(i % 5) + 1})`;

/** One stacked band of every item (coloured), then each group as rows on a common scale (largest item = full track). */
export function AllocationCard({ state, className = '' }: { state: State; className?: string }) {
  const { groups, debts } = state.allocation_groups;
  const empty = groups.length === 0;
  // Bars share one scale: the largest item fills the track; the % beside each is its true share.
  const top = Math.max(0.0001, ...groups.flatMap(g => g.items.map(i => i.ratio)));
  return (
    <section className={`card stretch alloc ${className}`} aria-labelledby="alloc-h">
      <header className="card-head">
        <h2 id="alloc-h">資產配置</h2>
        {!empty && (
          <span className="aside">
            {groups.map(g => (
              <span key={g.key}>
                {g.label} <span className="num strong ink">{pct(g.ratio)}</span>
              </span>
            ))}
          </span>
        )}
      </header>

      {empty ? (
        <p className="note">記下現金和持股後，這裡會顯示各類資產的比例。</p>
      ) : (
        <>
          <div
            className="band"
            role="img"
            aria-label={groups.flatMap(g => g.items.map(i => `${i.label} ${pct(i.ratio)}`)).join('，')}
          >
            {groups.map(g => (
              <span key={g.key} className="band-group" style={{ flexGrow: Math.max(g.ratio, 0.03) }}>
                {g.items.map((i, n) => (
                  <span key={i.label} style={{ flexGrow: i.ratio / (g.ratio || 1), background: swatch(g.key, n) }} title={`${i.label} ${pct(i.ratio)}`} />
                ))}
              </span>
            ))}
          </div>

          {groups.map(g => (
            <div key={g.key} className={`alloc-group alloc-${g.key}`}>
              <div className="alloc-head">
                <span>
                  {g.label}
                  <span className="num muted alloc-share">{pct(g.ratio)}</span>
                </span>
                <span className="num muted">
                  <Money value={g.value} />
                </span>
              </div>
              {g.items.map((i, n) => (
                <div key={i.label} className="alloc-row" style={{ '--c': swatch(g.key, n) } as React.CSSProperties}>
                  <span className="alloc-label">
                    <i aria-hidden />
                    {i.label}
                  </span>
                  <span className="alloc-bar" aria-hidden>
                    <span style={{ width: `${Math.max((i.ratio / top) * 100, 1.5)}%` }} />
                  </span>
                  <span className="num alloc-pct">{pct(i.ratio)}</span>
                  <Money className="num muted alloc-val" value={i.value} />
                </div>
              ))}
            </div>
          ))}

          {debts.length > 0 && (
            <div className="alloc-group alloc-debt">
              <div className="alloc-head">
                <span>負債</span>
                <span className="muted small">已從總資產扣除</span>
              </div>
              {debts.map(d => (
                <div key={d.label} className="alloc-row">
                  <span className="alloc-label">
                    <i aria-hidden />
                    {d.label}
                  </span>
                  <span />
                  <span />
                  <Money className="num alloc-val" value={d.value} />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

const amount = (s: string) => Number(s.replace(/[^\d.−-]/g, '').replace('−', '-'));
const signed = (n: number) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.round(Math.abs(n)).toLocaleString('en-US')}`;
const md = (d: string) => `${Number(d.slice(5, 7))}/${Number(d.slice(8))}`;

/** 本月／今年 change from the snapshots (or since the first one, while there is less history), and the high. */
function NetWorthChanges({ state }: { state: State }) {
  const h = state.history;
  if (h.length < 2) return null; // the card shows its first-days note then
  const now = amount(state.total);
  const today = state.today;
  // The base for a period: the last snapshot before it starts, else its first snapshot (labelled with its date).
  const since = (start: string) => {
    const before = h.filter(p => p.date < start);
    const p = before.length ? before[before.length - 1] : h.find(p => p.date >= start);
    return p && p.date < today ? { date: p.date, from: before.length > 0, value: amount(p.total) } : null;
  };
  const rows: { label: string; delta: number; base: number }[] = [];
  const month = since(`${today.slice(0, 7)}-01`);
  const year = since(`${today.slice(0, 4)}-01-01`);
  if (month) rows.push({ label: month.from ? '本月' : `從 ${md(month.date)} 起`, delta: now - month.value, base: month.value });
  if (year && (!month || year.date !== month.date)) rows.push({ label: year.from ? '今年' : `從 ${md(year.date)} 起`, delta: now - year.value, base: year.value });
  const high = h.reduce((best, p) => (amount(p.total) > amount(best.total) ? p : best), h[0]);
  const atHigh = now >= amount(high.total);
  return (
    <dl className="metrics">
      {rows.map(r => (
        <div key={r.label}>
          <dt>{r.label}</dt>
          <dd className={signClass(Math.sign(r.delta))}>
            {!(r.base > 0) && <Trend sign={Math.sign(r.delta)} />}
            <Money className="num" value={signed(r.delta)} />
            {r.base > 0 && (
              <span className="num pct trend">
                <Trend sign={Math.sign(r.delta)} />
                {`${r.delta >= 0 ? '+' : '−'}${Math.abs((r.delta / r.base) * 100).toFixed(2)}%`}
              </span>
            )}
          </dd>
        </div>
      ))}
      <div>
        <dt>最高點</dt>
        <dd>{atHigh ? <span className="small">就是現在</span> : <><Money className="num" value={signed(amount(high.total)).replace('+', '')} /><span className="num pct">{md(high.date)}</span></>}</dd>
      </div>
    </dl>
  );
}
