import { Money } from '../lib/privacy';
import { IconBadge } from '../lib/icons';
import type { State } from '../types';

/** 貸款: what is still owed on each loan account, how much is repaid and when it ends. */
export function LoansCard({ state, className = '' }: { state: State; className?: string }) {
  if (state.loans.length === 0) return null;
  return (
    <section className={`card ${className}`} aria-labelledby="loan-h">
      <header className="card-head">
        <h2 id="loan-h">貸款</h2>
        <span className="aside">每月還款：還 @{state.loans[0].name}</span>
      </header>
      <div className="table loan-t">
        <div className="thead" aria-hidden>
          <span>貸款</span>
          <span className="hide-sm">已還</span>
          <span className="hide-sm">每月</span>
          <span>剩餘本金</span>
        </div>
        {state.loans.map(l => (
          <div key={l.id} className="trow">
            <span className="cell-ic">
              <IconBadge name="loan" />
              <span className="cell">
                <span className="ellipsis">{l.name}</span>
                <span className="sub">
                  {l.done ? '已還清' : [l.rate && `年利率 ${l.rate}`, l.payoff && `預計 ${l.payoff.replace('-', '/')} 還清`].filter(Boolean).join('　') || '沒有填貸款條件'}
                </span>
              </span>
            </span>
            <span className="bar-cell hide-sm">
              {l.ratio != null && (
                <>
                  <span className="meter" aria-hidden>
                    <span style={{ width: `${l.ratio * 100}%` }} />
                  </span>
                  <span className="num small">{Math.round(l.ratio * 100)}%</span>
                </>
              )}
            </span>
            <span className="cell r hide-sm">
              {l.payment ? <Money className="num" value={l.payment} /> : <span className="muted small">—</span>}
              {l.months_left != null && <span className="sub">還有 {l.months_left} 期</span>}
            </span>
            <span className="cell r">
              <Money className="num" value={l.owed} />
              {l.interest_left && (
                <span className="sub">
                  利息還要 <Money className="num" value={l.interest_left} />
                </span>
              )}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
