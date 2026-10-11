import { useEffect, useState } from 'react';
import { api } from '../api';
import { Money } from '../lib/privacy';
import type { Advice as AdviceData, AdviceItem, Seg, State } from '../types';

const LEVEL_LABEL = { warn: '警示', note: '提醒', ok: '良好' } as const;

/** Text with TWD amounts that privacy mode hides. */
export function Segs({ parts }: { parts: Seg[] }) {
  return (
    <>
      {parts.map((p, i) => (typeof p === 'string' ? <span key={i}>{p}</span> : <Money key={i} className="num" value={p.m} />))}
    </>
  );
}

/** 健檢: rule-based checks on the ledger itself; refetched whenever the ledger changes. */
export function AdviceCard({ state }: { state: State }) {
  const [data, setData] = useState<AdviceData | null>(null);
  const [showOk, setShowOk] = useState(false);

  useEffect(() => {
    let live = true;
    void api.advice().then(r => {
      if (live && r.ok) setData(r.advice);
    });
    return () => {
      live = false;
    };
  }, [state]);

  if (!data || data.items.length === 0) return null;
  const open = data.items.filter(a => a.level !== 'ok');
  const ok = data.items.filter(a => a.level === 'ok');
  const warn = open.filter(a => a.level === 'warn').length;

  return (
    <section className="card span-12 advice" aria-labelledby="advice-h">
      <header className="card-head">
        <h2 id="advice-h">健檢</h2>
        <span className="aside">
          {warn > 0 && <span className="lv-warn">{warn} 項警示</span>}
          {open.length - warn > 0 && <span className="lv-note">{open.length - warn} 項提醒</span>}
          <span>{ok.length} 項良好</span>
        </span>
      </header>
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
        <span className="muted tiny">依你的帳本資料做的規則檢查，不是個股推薦</span>
      </footer>
    </section>
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
