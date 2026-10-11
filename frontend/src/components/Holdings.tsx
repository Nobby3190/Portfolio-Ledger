import { useState } from 'react';
import { Money, signClass } from '../lib/privacy';
import type { Closed, Holding, TxRow } from '../types';
import { TxLine } from './Activity';

interface Props {
  holdings: Holding[];
  closed: Closed[];
  value: string;
  unrealized: string;
  unrealizedSign: number;
  transactions: TxRow[];
  onEdit(id: number): void;
}

export function Holdings({ holdings, closed, value, unrealized, unrealizedSign, transactions, onEdit }: Props) {
  const [open, setOpen] = useState<string | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  if (holdings.length === 0 && closed.length === 0) return null;
  const txsOf = (ids: number[]) => transactions.filter(t => ids.includes(t.id));

  return (
    <section className="card span-12" aria-labelledby="holdings-h">
      <header className="card-head">
        <h2 id="holdings-h">持股</h2>
        {holdings.length > 0 && (
          <span className="aside">
            <span>{holdings.length} 檔</span>
            <span>
              市值 <Money className="num" value={value} />
            </span>
            <span className={signClass(unrealizedSign)}>
              未實現 <Money className="num" value={unrealized} />
            </span>
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
                      <span className="code">{h.symbol}</span>
                      <span className="ellipsis">{h.name}</span>
                    </span>
                    <span className="sub">佔總資產 {Math.round(h.weight * 100)}%</span>
                  </span>
                  <span className="cell r hide-sm">
                    <span className="num">{h.qty}</span>
                  </span>
                  <span className="cell r">
                    <span className="num">{h.close ?? '—'}</span>
                    {h.day_pct && <span className={`sub num ${signClass(h.day_sign)}`}>{h.day_pct}</span>}
                  </span>
                  <span className="cell r hide-sm">
                    <Money className="num" value={h.value_twd} />
                  </span>
                  <span className={`cell r ${signClass(h.sign)}`}>
                    <Money className="num" value={h.unrealized} />
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
                        <dd className={`num ${signClass(h.day_sign)}`}>
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
                      <div>
                        <dt>帳戶</dt>
                        <dd>{h.accounts.join('、')}</dd>
                      </div>
                    </dl>
                    <p className="note">未實現損益已扣除預估的賣出手續費和證交稅。點交易可以修改。</p>
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
                    <Money className="num" value={c.realized} />
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
