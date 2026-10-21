import { useEffect, useState } from 'react';
import { api } from '../api';
import { Money } from '../lib/privacy';
import type { Dividends, State } from '../types';

const md = (d: string) => `${Number(d.slice(5, 7))}/${Number(d.slice(8))}`;

/** 股利: last 12 months, yield on cost, share of spending, and coming 除息 (DESIGN.md v1.4).
 *  Refetched whenever the ledger changes; hidden until there is a dividend or an upcoming one. */
function useDividends(state: State) {
  const [data, setData] = useState<Dividends | null>(null);
  useEffect(() => {
    let live = true;
    void api.dividends().then(r => {
      if (live && r.ok) setData(r.dividends);
    });
    return () => {
      live = false;
    };
  }, [state]);
  return data;
}

/** 股利 tile beside the total (大膽版): the last 12 months, yield on cost, and each holding's share as one band. */
export function DividendsTile({ state }: { state: State }) {
  const data = useDividends(state);
  if (!data || !data.has) return null;
  // A plain card like 持股 and the rest (2026-10-21; was a solid teal tile).
  return (
    <section className="card div-tile" aria-labelledby="div-tile-h">
      <header className="card-head">
        <h2 id="div-tile-h">股利</h2>
        <span className="aside">近 12 個月</span>
      </header>
      <p className="div-tile-num">
        <Money className="num" value={data.ttm} />
      </p>
      <p className="div-tile-sub muted">
        {data.yield_on_cost && <span>成本殖利率 {data.yield_on_cost.replace(/^\+/, '')}</span>}
        {data.cover && <span>可支付生活支出 {data.cover.replace(/^\+/, '')}</span>}
      </p>
      {data.by_symbol.length > 1 && (
        <div className="div-tile-band" role="img" aria-label={data.by_symbol.map(s => `${s.symbol} ${Math.round(s.ratio * 100)}%`).join('，')}>
          {data.by_symbol.map((s, i) => (
            <span key={s.symbol} style={{ flexGrow: Math.max(s.ratio, 0.02), opacity: 1 - Math.min(i, 4) * 0.17 }} title={`${s.symbol} ${Math.round(s.ratio * 100)}%`} />
          ))}
        </div>
      )}
    </section>
  );
}

export function DividendsCard({ state }: { state: State }) {
  const data = useDividends(state);
  if (!data || !data.has) return null;
  const top = Math.max(...data.by_symbol.map(s => s.ratio), 0);

  return (
    <section className="card span-12" aria-labelledby="div-h">
      <header className="card-head">
        <h2 id="div-h">股利</h2>
        <span className="aside">近 12 個月</span>
      </header>
      <dl className="metrics div-metrics">
        <div>
          <dt>近 12 個月股利</dt>
          <dd>
            <Money className="num" value={data.ttm} />
          </dd>
        </div>
        <div>
          <dt>今年累計</dt>
          <dd>
            <Money className="num" value={data.ytd} />
          </dd>
        </div>
        {data.yield_on_cost && (
          <div>
            <dt>成本殖利率</dt>
            <dd className="num">{data.yield_on_cost.replace(/^\+/, '')}</dd>
          </div>
        )}
        {data.cover && (
          <div>
            <dt>可支付生活支出</dt>
            <dd className="num">{data.cover.replace(/^\+/, '')}</dd>
          </div>
        )}
      </dl>

      {data.by_symbol.length > 0 && (
        <div className="table div-t">
          <div className="thead" aria-hidden>
            <span>名稱</span>
            <span className="hide-sm">佔比</span>
            <span>近 12 個月</span>
          </div>
          {data.by_symbol.map(s => (
            <div key={s.symbol} className="trow">
              <span className="cell">
                <span className="main">
                  <span className="code">{s.symbol}</span>
                  <span className="ellipsis">{s.name}</span>
                </span>
                {!s.held && <span className="sub">已出清</span>}
              </span>
              <span className="bar-cell hide-sm">
                <span className="meter" aria-hidden>
                  <span style={{ width: `${top ? (s.ratio / top) * 100 : 0}%` }} />
                </span>
                <span className="num small">{Math.round(s.ratio * 100)}%</span>
              </span>
              <span className="cell r">
                <Money className="num" value={s.amount} />
              </span>
            </div>
          ))}
        </div>
      )}

      {data.upcoming.length > 0 && (
        <>
          <h3 className="sub-h">接下來 60 天除息</h3>
          <div className="table div-t">
            <div className="thead" aria-hidden>
              <span>名稱</span>
              <span className="hide-sm">每股</span>
              <span>預估入帳</span>
            </div>
            {data.upcoming.map(u => (
              <div key={`${u.symbol}-${u.ex_date}`} className="trow">
                <span className="cell">
                  <span className="main">
                    <span className="code">{u.symbol}</span>
                    <span className="ellipsis">{u.name}</span>
                  </span>
                  <span className="sub">
                    {md(u.ex_date)} 除息{u.pay_date ? `・${md(u.pay_date)} 發放` : ''}
                  </span>
                </span>
                <span className="cell r hide-sm">
                  <span className="num">{u.cash ?? '未公布'}</span>
                </span>
                <span className="cell r">{u.estimate ? <Money className="num" value={u.estimate} /> : <span className="muted small">—</span>}</span>
              </div>
            ))}
          </div>
        </>
      )}
      <p className="muted tiny">成本殖利率＝近 12 個月股利 ÷ 目前持股成本；預估入帳＝每股股利 × 目前股數，未扣二代健保。美股沒有除息預告。</p>
    </section>
  );
}
