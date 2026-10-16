import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Note, NoteInput } from '../types';
import { Sheet } from './Panels';

const slash = (d: string) => d.replace(/-/g, '/');

/** 投資筆記 inside a holding's or a watchlist row's detail: the user's own reasons, red lines, price band
 *  and review schedule (DESIGN.md v1.4). The app shows them back; it never judges them. */
export function NoteBlock(props: { symbol: string; name: string; today: string; initial?: Note | null; onChanged?(): void }) {
  const { symbol, name, initial, onChanged } = props;
  const [note, setNote] = useState<Note | null | undefined>(initial);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined) return setNote(initial);
    let live = true;
    void api.note(symbol).then(r => live && r.ok && setNote(r.note));
    return () => {
      live = false;
    };
  }, [symbol, initial]);

  const done = (n: Note | null) => {
    setNote(n);
    onChanged?.();
  };

  if (note === undefined) return null;
  const due = note?.review_due != null && note.review_due <= props.today;

  return (
    <div className="note-block">
      <div className="note-head">
        <h3 className="sub-h">投資筆記</h3>
        <span className="note-actions">
          {note?.review_months != null && (
            <button
              type="button"
              className={due ? 'chip' : 'quiet'}
              onClick={async () => {
                const r = await api.markReviewed(symbol);
                if (r.ok) done(r.note);
                else setError(r.error);
              }}
            >
              標記為已檢查
            </button>
          )}
          <button type="button" className="quiet" onClick={() => setEditing(true)}>
            {note ? '編輯' : '＋ 寫筆記'}
          </button>
        </span>
      </div>
      {!note && <p className="muted small">寫下為什麼買、什麼情況要重新想、合理價多少。價格跑出區間或到了檢查日，會在「提醒」裡出現。</p>}
      {note && (
        <dl className="note-body">
          {note.thesis && (
            <div>
              <dt>買入理由</dt>
              <dd>{note.thesis}</dd>
            </div>
          )}
          {note.red_lines.length > 0 && (
            <div>
              <dt>紅線</dt>
              <dd>
                <ul className="red-lines">
                  {note.red_lines.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </dd>
            </div>
          )}
          {(note.band_low || note.band_high) && (
            <div>
              <dt>合理價區間</dt>
              <dd className="num">
                {note.band_low ?? '—'} – {note.band_high ?? '—'}
              </dd>
            </div>
          )}
          {note.review_months != null && (
            <div>
              <dt>檢查</dt>
              <dd className={due ? 'warn' : ''}>
                每 {note.review_months} 個月・{note.last_review ? `上次 ${slash(note.last_review)}` : '還沒檢查過'}・下次 {slash(note.review_due ?? '')}
              </dd>
            </div>
          )}
        </dl>
      )}
      {error && <p className="message bad">{error}</p>}
      {editing && (
        <NoteSheet
          name={name}
          initial={note?.input ?? { symbol, thesis: '', red_lines: '', band_low: '', band_high: '', review_months: '', last_review: '' }}
          onClose={() => setEditing(false)}
          onSaved={n => {
            done(n);
            setEditing(false);
          }}
        />
      )}
    </div>
  );
}

function NoteSheet(props: { name: string; initial: NoteInput; onClose(): void; onSaved(n: Note | null): void }) {
  const [n, setN] = useState(props.initial);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (k: keyof NoteInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setN({ ...n, [k]: e.target.value });

  return (
    <Sheet title={`投資筆記　${props.name}`} onClose={props.onClose}>
      <form
        className="form"
        onSubmit={async e => {
          e.preventDefault();
          setSaving(true);
          const r = await api.saveNote(n);
          setSaving(false);
          if (r.ok) props.onSaved(r.note);
          else setError(r.error);
        }}
      >
        <label>
          買入理由
          <textarea rows={4} value={n.thesis} autoFocus onChange={set('thesis')} placeholder="為什麼買（或為什麼想買），200 字內" />
          <small className={`muted ${n.thesis.length > 200 ? 'warn' : ''}`}>{n.thesis.length} / 200</small>
        </label>
        <label>
          紅線
          <textarea rows={4} value={n.red_lines} onChange={set('red_lines')} placeholder={'出現就要重新想的事，一行一條\n例：毛利率連兩季低於 50%\n例：創辦人離職'} />
        </label>
        <div className="form-row">
          <label>
            合理價下限
            <input className="num" inputMode="decimal" value={n.band_low} onChange={set('band_low')} placeholder="可不填" />
          </label>
          <label>
            合理價上限
            <input className="num" inputMode="decimal" value={n.band_high} onChange={set('band_high')} placeholder="可不填" />
          </label>
        </div>
        <div className="form-row">
          <label>
            多久檢查一次（月）
            <input className="num" inputMode="numeric" value={n.review_months} onChange={set('review_months')} placeholder="空白＝不提醒" />
          </label>
          <label>
            上次檢查
            <input type="date" value={n.last_review} onChange={set('last_review')} />
          </label>
        </div>
        <small className="muted">價格用股票本身的幣別。全部清空再儲存會刪掉這份筆記。</small>
        {error && <p className="message bad">{error}</p>}
        <div className="actions">
          <button type="submit" className="primary" disabled={saving}>
            {saving ? '儲存中…' : '儲存'}
          </button>
          <button type="button" className="quiet" onClick={props.onClose}>
            取消
          </button>
        </div>
      </form>
    </Sheet>
  );
}
