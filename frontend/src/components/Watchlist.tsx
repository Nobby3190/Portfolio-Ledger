import { useEffect, useState } from 'react';
import { api } from '../api';
import { signClass, Trend } from '../lib/privacy';
import type { State, WatchRow } from '../types';
import { SymbolField } from './Composer';
import { FundamentalsBlock } from './Fundamentals';
import { NoteBlock } from './Notes';

/** 自選股: stocks the user is thinking of buying, with their own price band, notes and 財報快照 (DESIGN.md v1.4). */
export function WatchlistCard({ state }: { state: State }) {
  const [rows, setRows] = useState<WatchRow[] | null>(null);
  const [symbol, setSymbol] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = async () => {
    const r = await api.watchlist();
    if (r.ok) setRows(r.watchlist);
  };
  useEffect(() => {
    void load();
  }, [state]);

  async function add(s: string) {
    if (!s.trim()) return;
    setAdding(true);
    const r = await api.addWatch(s.trim());
    setAdding(false);
    if (!r.ok) return setError(r.error);
    setRows(r.watchlist);
    setSymbol('');
    setError(null);
    setOpen(r.symbol);
  }

  if (!rows) return null;
  return (
    <section className="card span-12" aria-labelledby="watch-h">
      <header className="card-head">
        <h2 id="watch-h">自選股</h2>
        {rows.length > 0 && <span className="aside">{rows.length} 檔</span>}
      </header>
      <form
        className="watch-add"
        onSubmit={e => {
          e.preventDefault();
          void add(symbol);
        }}
      >
        <SymbolField value={symbol} onChange={setSymbol} onPick={s => void add(s)} />
        <button type="submit" className="primary" disabled={adding || !symbol.trim()}>
          {adding ? '加入中…' : '加入'}
        </button>
      </form>
      {error && <p className="message bad">{error}</p>}
      {rows.length === 0 && <p className="muted small">打算買的股票放這裡：看漲跌、寫下想買的理由和合理價，價格進到區間時會在「資產」的提醒裡出現。</p>}
      {rows.length > 0 && (
        <div className="table watch-t">
          <div className="thead" aria-hidden>
            <span>名稱</span>
            <span>收盤</span>
            <span className="hide-sm">一週</span>
            <span>合理價區間</span>
          </div>
          {rows.map(w => {
            const isOpen = open === w.symbol;
            return (
              <div key={w.symbol}>
                <button type="button" className="trow" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : w.symbol)}>
                  <span className="cell">
                    <span className="main">
                      <span className="code">{w.symbol}</span>
                      <span className="ellipsis">{w.name}</span>
                    </span>
                    <span className="sub">
                      {w.market}
                      {w.close_date ? `・${Number(w.close_date.slice(5, 7))}/${Number(w.close_date.slice(8))} 收盤` : ''}
                    </span>
                  </span>
                  <span className="cell r">
                    <span className="num">{w.close ?? '—'}</span>
                    {w.day_pct && (
                      <span className={`sub num trend-line ${signClass(w.day_sign)}`}>
                        <Trend sign={w.day_sign} />
                        {w.day_pct}
                      </span>
                    )}
                  </span>
                  <span className={`cell r hide-sm ${signClass(w.week_sign)}`}>
                    {w.week_pct ? (
                      <span className="num trend-line">
                        <Trend sign={w.week_sign} />
                        {w.week_pct}
                      </span>
                    ) : (
                      <span className="muted small">—</span>
                    )}
                  </span>
                  <span className="cell r">
                    <span className="num">{w.band ?? <span className="muted small">未設定</span>}</span>
                    {w.band_where && <span className={`sub ${w.band_side !== 0 ? 'band-out' : ''}`}>{w.band_where}</span>}
                  </span>
                </button>
                {isOpen && (
                  <div className="detail">
                    <NoteBlock symbol={w.symbol} name={w.name} today={state.today} initial={w.note} onChanged={() => void load()} />
                    {w.kind === 'stock' && <FundamentalsBlock symbol={w.symbol} />}
                    <div className="actions">
                      <button
                        type="button"
                        className="quiet danger"
                        onClick={async () => {
                          const r = await api.removeWatch(w.symbol);
                          if (r.ok) setRows(r.watchlist);
                        }}
                      >
                        從自選股移除
                      </button>
                      <span className="muted tiny">投資筆記會保留，買進後在持股裡看得到</span>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
