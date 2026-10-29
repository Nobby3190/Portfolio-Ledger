import { useContext, useState } from 'react';
import { IconBadge, toneOf, txIcon } from '../lib/icons';
import { FreshContext } from '../lib/motion';
import { Money } from '../lib/privacy';
import type { TxRow } from '../types';

const PAGE = 30;
// The 資產 view lists investing and money movement; income/expense live in 收支.
const ASSET_KINDS = ['buy', 'holding_in', 'sell', 'cash_dividend', 'stock_dividend', 'split', 'deposit', 'withdraw', 'transfer', 'repay'];

export function Activity({ transactions: all, onEdit, className = '', initial = PAGE }: { transactions: TxRow[]; onEdit(id: number): void; className?: string; initial?: number }) {
  const [limit, setLimit] = useState(initial);
  const transactions = all.filter(t => ASSET_KINDS.includes(t.kind));
  if (transactions.length === 0) return null;

  return (
    <section className={`card ${className}`} aria-labelledby="activity-h">
      <header className="card-head">
        <h2 id="activity-h">投資與轉帳紀錄</h2>
        <span className="aside">點一筆可以修改</span>
      </header>
      <TxList rows={transactions.slice(0, limit)} onEdit={onEdit} />
      {transactions.length > limit && (
        <button type="button" className="quiet toggle" onClick={() => setLimit(limit + PAGE)}>
          顯示更早的 {Math.min(transactions.length - limit, PAGE)} 筆
        </button>
      )}
    </section>
  );
}

/** Rows grouped under month headings, newest first. */
export function TxList({ rows, onEdit, months = true }: { rows: TxRow[]; onEdit(id: number): void; months?: boolean }) {
  const groups = new Map<string, TxRow[]>();
  for (const t of rows) {
    const key = months ? t.date.slice(0, 7) : '';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(t);
  }
  return (
    <>
      {[...groups].map(([month, list]) => (
        <div key={month}>
          {month && <h3 className="month-h">{`${month.slice(0, 4)} 年 ${Number(month.slice(5))} 月`}</h3>}
          <div className="table tx-t">
            {list.map(t => (
              <TxLine key={t.id} t={t} onEdit={onEdit} />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

/** One transaction: what happened on the first line, the details under it, amount on the right. */
export function TxLine({ t, onEdit }: { t: TxRow; onEdit(id: number): void }) {
  const fresh = useContext(FreshContext).has(t.id);
  let title: string;
  const sub: string[] = [];
  if (t.kind === 'transfer') {
    title = `轉帳 ${t.account} → ${t.to_account}`;
    if (t.received) sub.push(`轉入 ${t.received}`);
  } else if (t.kind === 'repay') {
    title = `還款 ${t.account} → ${t.to_account}`;
  } else if (t.kind === 'income' || t.kind === 'expense') {
    title = t.category ?? t.label;
    sub.push(t.account);
  } else {
    title = t.symbol ? `${t.label} ${t.name ?? t.symbol}` : t.label;
    if (t.kind === 'buy' || t.kind === 'sell' || t.kind === 'holding_in') sub.push(`${t.qty} 股 @ ${t.price}`);
    else if (t.kind === 'stock_dividend') sub.push(`${t.qty} 股`);
    else if (t.kind === 'split') sub.push(`1 股變 ${t.ratio} 股`);
    sub.push(t.account);
  }
  // A 定期定額 buy still at the close price (its note changes once edited to the broker's fill).
  if (t.note) sub.push(t.dca && t.note === '定期定額' ? '定期定額・收盤價估算' : t.note);
  const amount = t.kind === 'transfer' ? t.amount?.replace(/^−/, '') ?? null : t.amount;
  return (
    <button type="button" className={`trow ${fresh ? 'fresh' : ''}`} title="點一下修改" onClick={() => onEdit(t.id)}>
      <span className="date num">{t.date.slice(5).replace('-', '/')}</span>
      <span className="cell-ic">
        <IconBadge name={txIcon(t.kind, t.category, t.note)} tone={toneOf(t.kind)} category={t.category} />
        <span className="cell">
          <span className="ellipsis">
            {title}
            {t.recurring && (
              <span className="rec-tag" title={t.dca ? '定期定額自動記入' : '週期性收支自動記入'}>
                {t.dca ? '定額' : '週期'}
              </span>
            )}
          </span>
          {sub.length > 0 && <span className="sub ellipsis">{sub.join('　')}</span>}
        </span>
      </span>
      <span className="cell r">
        <span>
          <Money className="num" value={amount} />
          {amount && t.currency !== 'TWD' && <span className="ccy-tag">{t.currency}</span>}
        </span>
      </span>
    </button>
  );
}
