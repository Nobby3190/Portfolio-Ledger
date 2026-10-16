import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../api';
import { Icon } from '../lib/icons';
import { Money } from '../lib/privacy';
import type { Advice as AdviceData, AdviceItem, Seg, State } from '../types';
import { Sheet } from './Panels';

const LEVEL_LABEL = { warn: '警示', note: '提醒', ok: '良好' } as const;

/** Text with TWD amounts that privacy mode hides. */
export function Segs({ parts }: { parts: Seg[] }) {
  return (
    <>
      {parts.map((p, i) => (typeof p === 'string' ? <span key={i}>{p}</span> : <Money key={i} className="num" value={p.m} />))}
    </>
  );
}

/** 健檢 results, refetched whenever the ledger changes. */
function useAdvice(state: State): AdviceData | null {
  const [data, setData] = useState<AdviceData | null>(null);
  useEffect(() => {
    let live = true;
    void api.advice().then(r => {
      if (live && r.ok) setData(r.advice);
    });
    return () => {
      live = false;
    };
  }, [state]);
  return data;
}

/** 健檢 lives behind a report icon in the top bar (資產 only): not something to read every day, so the
 *  page doesn't spend a full-width card on it (2026-10-15). The badge counts warnings and notes. */
export function AdviceButton({ state }: { state: State }) {
  const data = useAdvice(state);
  const [open, setOpen] = useState(false);
  if (!data || data.items.length === 0) return null;
  const warn = data.items.filter(a => a.level === 'warn').length;
  const note = data.items.filter(a => a.level === 'note').length;
  const label = `健檢${warn ? `，${warn} 項警示` : ''}${note ? `，${note} 項提醒` : ''}`;
  return (
    <>
      <button type="button" className="icon-btn" title={label} aria-label={label} onClick={() => setOpen(true)}>
        <Icon name="report" size={20} />
        {warn + note > 0 && (
          <span className={`count-badge ${warn ? 'lv-warn' : 'lv-note'}`} aria-hidden>
            {warn + note}
          </span>
        )}
      </button>
      {/* The top bar's backdrop blur would make it the sheet's containing block: render at the page level. */}
      {open &&
        createPortal(
          <Sheet title="健檢" onClose={() => setOpen(false)} wide>
            <AdviceBody data={data} />
          </Sheet>,
          document.body,
        )}
    </>
  );
}

function AdviceBody({ data }: { data: AdviceData }) {
  const [showOk, setShowOk] = useState(false);
  const open = data.items.filter(a => a.level !== 'ok');
  const ok = data.items.filter(a => a.level === 'ok');
  const warn = open.filter(a => a.level === 'warn').length;
  return (
    <div className="advice advice-sheet">
      <p className="aside">
        {warn > 0 && <span className="lv-warn">{warn} 項警示　</span>}
        {open.length - warn > 0 && <span className="lv-note">{open.length - warn} 項提醒　</span>}
        <span className="muted">{ok.length} 項良好</span>
      </p>
      <ul className="advice-list">
        {open.map(a => (
          <AdviceRow key={a.key} a={a} />
        ))}
        {showOk && ok.map(a => <AdviceRow key={a.key} a={a} />)}
      </ul>
      {open.length === 0 && !showOk && <p className="muted small">目前沒有需要注意的地方。</p>}
      <footer className="advice-foot">
        {ok.length > 0 && (
          <button type="button" className="quiet" onClick={() => setShowOk(!showOk)}>
            {showOk ? '收起正常項目' : `另有 ${ok.length} 項正常`}
          </button>
        )}
        <span className="muted tiny">依你的帳本資料做的規則檢查，不是個股推薦；門檻在設定裡改</span>
      </footer>
    </div>
  );
}

function AdviceRow({ a }: { a: AdviceItem }) {
  return (
    <li className={`advice-row lv-${a.level}`}>
      <span className="lv-dot" aria-hidden />
      <span className="advice-title">
        {a.title}
        <span className="visually-hidden">（{LEVEL_LABEL[a.level]}）</span>
      </span>
      <span className="advice-body">
        <span>
          <Segs parts={a.detail} />
        </span>
        {a.action && (
          <span className="advice-action">
            <Segs parts={a.action} />
          </span>
        )}
      </span>
    </li>
  );
}
