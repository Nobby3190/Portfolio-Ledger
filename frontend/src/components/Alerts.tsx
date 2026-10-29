import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../api';
import { Icon } from '../lib/icons';
import type { AlertItem, Alerts as AlertsData, State } from '../types';
import { Segs } from './Advice';
import { Sheet } from './Panels';

const LEVEL_LABEL = { warn: '警示', note: '提醒', ok: '資訊' } as const;

/** 提醒: price moves, the user's price band, review dates and coming 除息 for holdings and the watchlist,
 *  and the bills of cards paid by 自動扣繳. A blinking bell in the top bar of every view (beside 健檢 on
 *  資產) while any is left; it goes once every one is dismissed (2026-10-20, was a card beside 持股).
 *  A toast says when a refresh brought new ones. */
export function AlertsButton({ state, onToast }: { state: State; onToast(text: string): void }) {
  const [data, setData] = useState<AlertsData | null>(null);
  const [open, setOpen] = useState(false);
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

  if (!data || (data.items.length === 0 && !open)) return null;
  const take = (r: AlertsRes) => r.ok && setData(r.alerts);
  const n = data.items.length;
  const warn = data.items.some(a => a.level === 'warn');
  const label = `提醒，${n} 則`;

  return (
    <>
      {n > 0 && (
        <button type="button" className="icon-btn blink" title={label} aria-label={label} onClick={() => setOpen(true)}>
          <Icon name="bell" size={20} />
          <span className={`count-badge ${warn ? 'lv-warn' : 'lv-note'}`} aria-hidden>
            {n}
          </span>
        </button>
      )}
      {/* The top bar's backdrop blur would make it the sheet's containing block: render at the page level. */}
      {open &&
        createPortal(
          <Sheet title="提醒" onClose={() => setOpen(false)} wide>
            <AlertsBody data={data} take={take} />
          </Sheet>,
          document.body,
        )}
    </>
  );
}

type AlertsRes = { ok: true; alerts: AlertsData } | { ok: false; error: string };

function AlertsBody({ data, take }: { data: AlertsData; take(r: AlertsRes): void }) {
  return (
    <div className="advice advice-sheet alerts">
      <p className="aside">{data.items.length > 0 ? `${data.items.length} 則` : '都看過了。'}</p>
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
        <span className="muted tiny">依收盤價、你寫的投資筆記和信用卡帳單，門檻在設定裡改</span>
      </footer>
    </div>
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
