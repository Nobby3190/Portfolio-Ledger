import { useState } from 'react';
import { Money, signClass, Trend } from '../lib/privacy';
import type { Closed, Holding, TxRow } from '../types';
import { TxLine } from './Activity';
import { FundamentalsBlock } from './Fundamentals';
import { NoteBlock } from './Notes';

interface Props {
  holdings: Holding[];
  closed: Closed[];
  value: string;
  unrealized: string;
  unrealizedSign: number;
  unrealizedPct: string | null;
  dayChange: string;
  dayChangePct: string | null;
  daySign: number;
  totalReturn: string;
  totalReturnPct: string | null;
  returnSign: number;
  xirr: string | null;
  transactions: TxRow[];
  today: string;
  onEdit(id: number): void;
  onBuy(): void;
}

/** 持股: first card under the totals, since tracking investments is what the app is for (2026-10-13).
 *  Every investment figure is shown here and only here: value, unrealized, day change, total return. */
export function Holdings(props: Props) {
  const { holdings, closed, transactions, onEdit, onBuy } = props;
  const [open, setOpen] = useState<string | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  if (holdings.length === 0 && closed.length === 0) {
    return (
      <section className="card span-8" aria-labelledby="holdings-h">
        <header className="card-head">
          <h2 id="holdings-h">投資</h2>
          <button type="button" className="primary" onClick={onBuy}>
            ＋ 記一筆買進
          </button>
        </header>
        <p className="muted">記下買進的股票或 ETF 後，這裡會顯示每一檔的市值、損益和每天的漲跌。以前買的可以勾「補登過去買的股票」，不會再扣現金。</p>
      </section>
    );
  }
  const txsOf = (ids: number[]) => transactions.filter(t => ids.includes(t.id));
  const top = Math.max(0.0001, ...holdings.map(h => h.weight));

  return (
    <section className="card span-8" aria-labelledby="holdings-h">
      <header className="card-head">
        <h2 id="holdings-h">持股</h2>
        {holdings.length > 0 && (
          <span className="aside">
            {holdings.length} 檔
            {/* 市值、未實現、最近交易日 sit on the 持股 tile beside the total (大膽版); the total return stays here */}
            <span className={`trend-line ${signClass(props.returnSign)}`}>
              總報酬 <Trend sign={props.returnSign} />
              <Money className="num" value={props.totalReturn} />
              {props.totalReturnPct && <span className="num">（{props.totalReturnPct}）</span>}
            </span>
            {props.xirr && <span className="num">年化 {props.xirr}</span>}
          </span>
        )}
      </header>
      {holdings.length > 0 && (
        <div className="table holdings-t">
          <div className="thead" aria-hidden>
            <span>名稱</span>
            <span className="hide-sm">股數</span>
            <span>現價</span>
            <span className="hide-sm">市值</span>
            <span>未實現損益</span>
          </div>
          {holdings.map(h => {
            const isOpen = open === h.symbol;
            return (
              <div key={h.symbol}>
                <button type="button" className="trow" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : h.symbol)}>
                  <span className="cell">
                    <span className="main">
                      <span className="code" style={{ '--t': marketTone(h.currency) } as React.CSSProperties}>
                        {h.symbol}
                      </span>
                      <span className="ellipsis">{h.name}</span>
                    </span>
                    <span className="sub weight-line">
                      <span className="meter" aria-hidden style={{ '--t': marketTone(h.currency) } as React.CSSProperties}>
                        <span style={{ width: `${Math.min(h.weight / top, 1) * 100}%` }} />
                      </span>
                      佔總資產 {Math.round(h.weight * 100)}%
                    </span>
                  </span>
                  <span className="cell r hide-sm">
                    <span className="num">{h.qty}</span>
                  </span>
                  <span className="cell r">
                    <span className="num">{h.close ?? '—'}</span>
                    {h.day_pct && (
                      <span className={`sub num trend-line ${signClass(h.day_sign)}`}>
                        <Trend sign={h.day_sign} />
                        {h.day_pct}
                      </span>
                    )}
                  </span>
                  <span className="cell r hide-sm">
                    <Money className="num" value={h.value_twd} />
                  </span>
                  <span className={`cell r ${signClass(h.sign)}`}>
                    <span className="trend-line">
                      <Trend sign={h.sign} />
                      <Money className="num" value={h.unrealized} />
                    </span>
                    <span className="sub num" style={{ color: 'inherit' }}>
                      {h.unrealized_pct}
                    </span>
                  </span>
                </button>
                {isOpen && (
                  <div className="detail">
                    <dl className="facts">
                      <div>
                        <dt>平均成本{h.cost_currency !== h.currency ? `（${h.cost_currency}，含換匯）` : ''}</dt>
                        <dd className="num">{h.avg_cost}</dd>
                      </div>
                      <div>
                        <dt>收盤日</dt>
                        <dd>{h.close_date ?? '—'}</dd>
                      </div>
                      <div>
                        <dt>最近交易日漲跌</dt>
                        <dd className={`num trend-line ${signClass(h.day_sign)}`}>
                          <Trend sign={h.day_sign} />
                          <Money value={h.day_change} />
                        </dd>
                      </div>
                      {h.currency !== 'TWD' && (
                        <div>
                          <dt>市值（{h.currency}）</dt>
                          <dd className="num">
                            <Money value={h.value} />
                          </dd>
                        </div>
                      )}
                      {h.realized && (
                        <div>
                          <dt>已實現</dt>
                          <dd className="num">
                            <Money value={h.realized} />
                          </dd>
                        </div>
                      )}
                      {h.dividends && (
                        <div>
                          <dt>累計股利</dt>
                          <dd className="num">
                            <Money value={h.dividends} />
                          </dd>
                        </div>
                      )}
                      {h.dividends_ttm && (
                        <div>
                          <dt>近 12 個月股利</dt>
                          <dd className="num">
                            <Money value={h.dividends_ttm} />
                            {h.yield_on_cost && <span className="muted">（成本殖利率 {h.yield_on_cost}）</span>}
                          </dd>
                        </div>
                      )}
                      {h.xirr && (
                        <div>
                          <dt>年化報酬</dt>
                          <dd className="num">{h.xirr}</dd>
                        </div>
                      )}
                      <div>
                        <dt>帳戶</dt>
                        <dd>{h.accounts.join('、')}</dd>
                      </div>
                    </dl>
                    <p className="note">未實現損益已扣除預估的賣出手續費和證交稅。點交易可以修改。</p>
                    <NoteBlock symbol={h.symbol} name={h.name} today={props.today} />
                    <FundamentalsBlock symbol={h.symbol} />
                    <div className="table tx-t">
                      {txsOf(h.tx_ids).map(t => (
                        <TxLine key={t.id} t={t} onEdit={onEdit} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {closed.length > 0 && (
        <>
          <button type="button" className="quiet toggle" aria-expanded={showClosed} onClick={() => setShowClosed(!showClosed)}>
            {showClosed ? '收起已出清' : `已出清 ${closed.length} 檔`}
          </button>
          {showClosed && (
            <div className="table closed-t">
              <div className="thead" aria-hidden>
                <span>名稱</span>
                <span>股利</span>
                <span>已實現損益</span>
              </div>
              {closed.map(c => (
                <div key={c.symbol} className="trow">
                  <span className="cell">
                    <span className="main">
                      <span className="code">{c.symbol}</span>
                      <span className="ellipsis">{c.name}</span>
                    </span>
                  </span>
                  <span className="cell r">
                    <Money className="num" value={c.dividends ?? '—'} />
                  </span>
                  <span className={`cell r ${signClass(c.sign)}`}>
                    <span className="trend-line">
                      <Trend sign={c.sign} />
                      <Money className="num" value={c.realized} />
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

/** Ticker chips and weight bars take the market's colour: 台股 indigo, 美股 sky, others plum. */
const marketTone = (currency: string) => (currency === 'TWD' ? 'var(--tone-indigo)' : currency === 'USD' ? 'var(--tone-sky)' : 'var(--tone-plum)');
