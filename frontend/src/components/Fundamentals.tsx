import { useState } from 'react';
import { api } from '../api';
import type { Fundamentals } from '../types';

const STATUS = { pass: '通過', fail: '沒過', na: '資料不足' } as const;

/** 財報快照 inside a holding's or a watchlist row's detail (DESIGN.md v1.4). Loaded on demand: the first
 *  open fetches from FinMind／Yahoo, later ones use the copy kept for 7 days. Numbers only, no verdict. */
export function FundamentalsBlock({ symbol }: { symbol: string }) {
  const [data, setData] = useState<Fundamentals | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  async function load(force = false) {
    setLoading(true);
    const r = await api.fundamentals(symbol, force);
    setLoading(false);
    if (r.ok) {
      setData(r.fundamentals);
      setError(null);
    } else setError(r.error);
  }

  async function copy(text: string) {
    const r = await api.copyText(text);
    setCopied(r.ok ? text : null);
    if (!r.ok) setError(r.error);
  }

  if (!data) {
    return (
      <div className="fund-block">
        <button type="button" className="quiet" disabled={loading} onClick={() => void load()}>
          {loading ? '抓取財報中…' : '▸ 財報快照'}
        </button>
        {error && <p className="message bad">{error}</p>}
      </div>
    );
  }

  const fails = data.checks?.filter(c => c.status === 'fail').length ?? 0;
  return (
    <div className="fund-block">
      <div className="note-head">
        <h3 className="sub-h">財報快照</h3>
        {data.available && (
          <button type="button" className="quiet" disabled={loading} onClick={() => void load(true)}>
            {loading ? '抓取中…' : '重新抓取'}
          </button>
        )}
      </div>
      {!data.available && <p className="muted small">{data.reason}</p>}
      {data.available && (
        <>
          {data.valuation && (
            <p className="small">
              本益比 <span className="num">{data.valuation.pe ?? '—（虧損）'}</span>　股價淨值比 <span className="num">{data.valuation.pb ?? '—'}</span>　殖利率{' '}
              <span className="num">{data.valuation.dividend_yield ?? '—'}</span>
            </p>
          )}
          {data.error && (
            <p className="message bad">
              {data.error}
              {data.table ? '（下面是之前抓的資料）' : ''}
            </p>
          )}
          {data.table && (
            <div className="fund-scroll">
              <table className="fund-t">
                <thead>
                  <tr>
                    <th>單位：{data.unit}</th>
                    {data.table.years.map(y => (
                      <th key={y} className="num">
                        {y}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.table.rows.map(r => (
                    <tr key={r.key}>
                      <th>{r.label}</th>
                      {r.values.map((v, i) => (
                        <td key={i} className="num">
                          {v ?? '—'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.checks && data.checks.length > 0 && (
            <>
              <h4 className="fund-h">
                去劣 7 條<span className="muted">　{fails > 0 ? `${fails} 條沒過` : '沒有沒過的'}</span>
              </h4>
              <ul className="fund-checks">
                {data.checks.map(c => (
                  <li key={c.key} className={`fc-${c.status}`}>
                    <span className="fc-status">{STATUS[c.status]}</span>
                    <span className="fc-label">{c.label}</span>
                    <span className="num">{c.value ?? '—'}</span>
                    <span className="muted small">
                      {c.rule}
                      {c.note ? `・${c.note}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="muted tiny">
            公開財報數字整理，不是投資建議。資料：{data.source ?? '—'}，{data.fetched_at ?? '—'} 抓取；銀行、保險和投入期、主動低毛利的公司，沒過不代表不好，要自己判斷。
          </p>
        </>
      )}
      {data.commands && data.commands.length > 0 && (
        <div className="fund-cmds">
          <span className="muted small">交給 ai-berkshire 深入分析（複製後貼到 Claude Code）：</span>
          {data.commands.map(c => (
            <button key={c.text} type="button" className="chip" title={c.text} onClick={() => void copy(c.text)}>
              {copied === c.text ? '已複製' : c.label}
            </button>
          ))}
        </div>
      )}
      {error && <p className="message bad">{error}</p>}
    </div>
  );
}
