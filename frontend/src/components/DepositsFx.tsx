import { Money, signClass } from '../lib/privacy';
import type { State } from '../types';

export function DepositsFx({ state, className = '' }: { state: State; className?: string }) {
  const { deposits, fx_positions: fx } = state;
  if (deposits.length === 0 && fx.length === 0) return null;
  return (
    <section className={`card ${className}`} aria-labelledby="dfx-h">
      <header className="card-head">
        <h2 id="dfx-h">定存與外幣</h2>
      </header>
      <div className="table deposit-t">
        <div className="thead" aria-hidden>
          <span>項目</span>
          <span className="hide-sm">狀態</span>
          <span>金額</span>
        </div>
        {deposits.map(d => (
          <div key={d.id} className="trow">
            <span className="cell">
              <span className="ellipsis">{d.name}</span>
              <span className="sub">
                年利率 {d.rate ?? '未填'}
                {d.maturity_date && `　${d.maturity_date} 到期`}
              </span>
            </span>
            <span className={`cell r hide-sm ${d.matured || d.soon ? 'warn' : ''}`}>
              <span>{d.matured ? '已到期' : d.days_left != null ? `還有 ${d.days_left} 天` : ''}</span>
              {d.matured && <span className="sub warn">記利息後轉回</span>}
            </span>
            <span className="cell r">
              <Money className="num" value={d.principal} />
              {d.accrued && (
                <span className="sub">
                  利息 <Money className="num" value={d.accrued} />
                </span>
              )}
            </span>
          </div>
        ))}
        {fx.map(f => (
          <div key={f.currency} className="trow">
            <span className="cell">
              <span className="main">
                <span className="code">{f.currency}</span>
                <span>{f.name}現金</span>
              </span>
              <span className="sub num">
                {f.avg_rate ? `成本匯率 ${f.avg_rate}　現在 ${f.rate ?? '—'}` : f.rate ? `匯率 ${f.rate}` : '還沒有匯率'}
              </span>
            </span>
            <span className={`cell r hide-sm ${signClass(f.sign)}`}>
              {f.gain && (
                <>
                  <Money className="num" value={f.gain} />
                  <span className="sub" style={{ color: 'inherit' }}>
                    匯差
                  </span>
                </>
              )}
            </span>
            <span className="cell r">
              <span>
                <Money className="num" value={f.balance} />
                <span className="ccy-tag">{f.currency}</span>
              </span>
              {f.value_twd && (
                <span className="sub">
                  ≈ <Money className="num" value={f.value_twd} />
                </span>
              )}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
