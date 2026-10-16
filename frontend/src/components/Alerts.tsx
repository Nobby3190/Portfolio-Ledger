import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { AlertItem, Alerts as AlertsData, State } from '../types';
import { Segs } from './Advice';

const LEVEL_LABEL = { warn: '警示', note: '提醒', ok: '資訊' } as const;

/** 提醒: price moves, the user's price band, review dates and coming 除息 for holdings and the watchlist.
 *  Shown at the top of 資產 only when there is something; a toast says when a refresh brought new ones. */
export function AlertsCard({ state, onToast, className = 'span-12' }: { state: State; onToast(text: string): void; className?: string }) {
  const [data, setData] = useState<AlertsData | null>(null);
  const known = useRef<Set<string> | null>(null);
  const refreshedAt = useRef(state.quotes.refreshed_at);

  useEffect(() => {
    let live = true;
    void api.alerts().then(r => {
      if (!live || !r.ok) return;
      const keys = new Set(r.alerts.items.map(a => a.key));
      // Only a quote refresh announces itself; opening the app or saving a note does not.
      if (known.current && state.quotes.refreshed_at !== refreshedAt.current) {
        const added = [...keys].filter(k => !known.current!.has(k)).length;
        if (added > 0) onToast(`有 ${added} 則新提醒`);
      }
      known.current = keys;
      refreshedAt.current = state.quotes.refreshed_at;
      setData(r.alerts);
    });
    return () => {
      live = false;
    };
  }, [state]);

  if (!data || data.items.length === 0) return null;
  const take = (r: { ok: true; alerts: AlertsData } | { ok: false; error: string }) => r.ok && setData(r.alerts);

  return (
    <section className={`card advice alerts ${className}`} aria-labelledby="alerts-h">
      <header className="card-head">
        <h2 id="alerts-h">提醒</h2>
        <span className="aside">{data.items.length} 則</span>
      </header>
      <ul className="advice-list">
        {data.items.map(a => (
          <AlertRow
            key={a.key}
            a={a}
            onDismiss={async () => take(await api.dismissAlert(a.key))}
            onReviewed={async () => {
              const r = await api.markReviewed(a.symbol);
              if (r.ok) take(await api.alerts());
            }}
          />
        ))}
      </ul>
      <footer className="advice-foot">
        <span className="muted tiny">依收盤價和你自己寫的投資筆記，門檻在設定裡改</span>
      </footer>
    </section>
  );
}

function AlertRow({ a, onDismiss, onReviewed }: { a: AlertItem; onDismiss(): void; onReviewed(): void }) {
  return (
    <li className={`advice-row lv-${a.level}`}>
      <span className="lv-dot" aria-hidden />
      <span className="advice-title">
        {a.title}
        <span className="visually-hidden">（{LEVEL_LABEL[a.level]}）</span>
        {!a.held && <span className="alert-tag">自選股</span>}
      </span>
      <span className="advice-body">
        <span>
          <Segs parts={a.detail} />
        </span>
        {a.red_lines.length > 0 && (
          <span className="alert-red">
            你寫的紅線：{a.red_lines.join('；')}
          </span>
        )}
        {a.action && (
          <span className="advice-action">
            <Segs parts={a.action} />
          </span>
        )}
      </span>
      <span className="alert-btn">
        {a.kind === 'review' ? (
          <button type="button" className="chip" onClick={onReviewed}>
            標記為已檢查
          </button>
        ) : (
          <button type="button" className="quiet" onClick={onDismiss}>
            知道了
          </button>
        )}
      </span>
    </li>
  );
}
