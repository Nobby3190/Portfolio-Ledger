import { useCallback, useEffect, useState } from 'react';
import { api } from './api';
import { Activity } from './components/Activity';
import { AdviceCard } from './components/Advice';
import { RecurringPanel, SearchPanel } from './components/Bookkeeping';
import { Composer, type ComposerOpen } from './components/Composer';
import { DepositsFx } from './components/DepositsFx';
import { Holdings } from './components/Holdings';
import { LoansCard } from './components/Loans';
import { MoneyView } from './components/MoneyView';
import { AccountsPanel, SettingsPanel } from './components/Panels';
import { PlanView } from './components/PlanView';
import { AllocationCard, NetWorthCard } from './components/Summary';
import { Icon } from './lib/icons';
import { FreshContext } from './lib/motion';
import { PrivacyContext } from './lib/privacy';
import type { State } from './types';

type Panel = 'accounts' | 'settings' | 'search' | 'recurring' | null;
type View = 'assets' | 'money' | 'plan';
const VIEWS: [View, string][] = [
  ['assets', '資產'],
  ['money', '收支'],
  ['plan', '規劃'],
];

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>(null);
  const [view, setViewState] = useState<View>('assets');
  const [composer, setComposer] = useState<ComposerOpen | null>(null);
  const [back, setBack] = useState<Panel>(null); // the panel to return to after editing from it
  const [toast, setToast] = useState<{ text: string; ok: boolean; n: number } | null>(null);
  const [fresh, setFresh] = useState<ReadonlySet<number>>(new Set());
  const say = useCallback((text: string, ok = true) => setToast(t => ({ text, ok, n: (t?.n ?? 0) + 1 })), []);

  const setView = useCallback((v: View) => {
    setViewState(v);
    window.scrollTo(0, 0);
  }, []);

  const load = useCallback(async () => {
    const r = await api.state();
    if (r.ok) {
      setState(r.state);
      setLoadError(null);
    } else setLoadError(r.error);
  }, []);

  useEffect(() => {
    void load();
    window.ledgerChanged = () => void load();
    return () => {
      window.ledgerChanged = undefined;
    };
  }, [load]);

  // First launch: nothing to do until there is an account.
  useEffect(() => {
    if (state && state.accounts.length === 0) setPanel('accounts');
  }, [state?.accounts.length]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  useEffect(() => {
    if (fresh.size === 0) return;
    const t = setTimeout(() => setFresh(new Set()), 2400);
    return () => clearTimeout(t);
  }, [fresh]);

  // The dark hero cards carry a faint glow that follows the pointer (CSS reads --mx/--my).
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const card = (e.target as Element | null)?.closest?.<HTMLElement>('.card.hero');
      if (!card) return;
      const r = card.getBoundingClientRect();
      card.style.setProperty('--mx', `${e.clientX - r.left}px`);
      card.style.setProperty('--my', `${e.clientY - r.top}px`);
    };
    document.addEventListener('pointermove', onMove);
    return () => document.removeEventListener('pointermove', onMove);
  }, []);

  const togglePrivacy = useCallback(async () => {
    if (!state) return;
    const r = await api.saveSettings({ privacy: state.settings.privacy === '1' ? '0' : '1' });
    if (r.ok) setState(r.state);
  }, [state]);

  const edit = useCallback(async (id: number) => {
    const r = await api.txFields(id);
    if (r.ok) setComposer({ editId: id, fields: r.fields });
    else say(r.error, false);
  }, [say]);

  // Editing a search result: the composer replaces the panel, which comes back when it closes.
  const editFromSearch = useCallback(
    (id: number) => {
      setPanel(null);
      setBack('search');
      void edit(id);
    },
    [edit],
  );
  const closeComposer = useCallback(() => {
    setComposer(null);
    setPanel(back);
    setBack(null);
  }, [back]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.metaKey) return;
      const k = e.key.toLowerCase();
      if (k === 'k') {
        // ⌘N never reaches the page inside the native window, so ⌘K opens the composer.
        e.preventDefault();
        setPanel(null);
        setComposer(c => c ?? { editId: null });
      } else if (k === 'h' && e.shiftKey) {
        e.preventDefault();
        void togglePrivacy();
      } else if (k === '1' || k === '2' || k === '3') {
        e.preventDefault();
        setView(VIEWS[Number(k) - 1][0]);
      } else if (k === ',') {
        e.preventDefault();
        setPanel('settings');
      } else if (k === 'f') {
        e.preventDefault();
        setComposer(null);
        setPanel('search');
      } else if (k === 'r') {
        e.preventDefault();
        void api.refresh().then(load);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [togglePrivacy, load, setView]);

  if (!state) {
    return (
      <main className="page">
        {loadError ? (
          <p className="message bad">{loadError}</p>
        ) : (
          <div className="grid" aria-busy="true" aria-label="載入中">
            <div className="card skel tall span-7" />
            <div className="card skel tall span-5" />
            <div className="card skel span-12" />
          </div>
        )}
      </main>
    );
  }

  const hidden = state.settings.privacy === '1';
  const q = state.quotes;

  return (
    <PrivacyContext.Provider value={hidden}>
      <div className={`app up-${state.settings.up_color}`}>
        <header className="topbar">
          <div className="topbar-in">
            <span className="brand" aria-label="帳本 Ledger">
              <span className="brand-mark" aria-hidden />
              帳本
              <span className="brand-en">Ledger</span>
            </span>
            <nav className="views" aria-label="視圖" style={{ '--i': VIEWS.findIndex(([v]) => v === view) } as React.CSSProperties}>
              <span className="views-pill" aria-hidden />
              {VIEWS.map(([v, label], i) => (
                <button key={v} type="button" className={view === v ? 'on' : ''} aria-current={view === v ? 'page' : undefined} title={`⌘${i + 1}`} onClick={() => setView(v)}>
                  {label}
                </button>
              ))}
            </nav>
            <span className="topbar-actions">
              <button
                type="button"
                className="quiet status"
                onClick={() => void api.refresh().then(load)}
                title={q.errors.join('\n') || '重新抓報價（⌘R）'}
              >
                {q.running ? '更新報價中…' : q.errors.length ? `報價更新失敗（${q.errors.length}）` : quoteLabel(q.latest, q.oldest)}
              </button>
              <button type="button" className="quiet" onClick={togglePrivacy} aria-pressed={hidden} title="⌘⇧H">
                {hidden ? '顯示金額' : '隱藏金額'}
              </button>
              <button type="button" className="quiet" onClick={() => setPanel('accounts')}>
                帳戶
              </button>
              <button type="button" className="quiet" onClick={() => setPanel('settings')} title="⌘,">
                設定
              </button>
              <button type="button" className="primary add" onClick={() => setComposer({ editId: null })} title="⌘K">
                ＋ 記一筆
              </button>
            </span>
          </div>
        </header>

        <FreshContext.Provider value={fresh}>
          <main className="page">
            {state.missing_fx.length > 0 && (
              <p className="message bad span-12">還沒有 {state.missing_fx.join('、')} 匯率，這些帳戶暫時不計入總資產；連上網路後會自動更新。</p>
            )}
            {view === 'assets' && (
              <div className="grid">
                <NetWorthCard state={state} className="span-7" />
                <AllocationCard state={state} className="span-5" />
                <AdviceCard state={state} />
                {state.transactions.length === 0 && state.accounts.length > 0 && <FirstSteps onAdd={() => setComposer({ editId: null })} />}
                <Holdings
                  holdings={state.holdings}
                  closed={state.closed}
                  value={state.holdings_value}
                  unrealized={state.holdings_unrealized}
                  unrealizedSign={state.holdings_unrealized_sign}
                  transactions={state.transactions}
                  onEdit={edit}
                />
                <LoansCard state={state} className="span-12" />
                {state.deposits.length + state.fx_positions.length > 0 ? (
                  <>
                    <DepositsFx state={state} className="span-6" />
                    <Activity transactions={state.transactions} onEdit={edit} className="span-6" initial={8} />
                  </>
                ) : (
                  <Activity transactions={state.transactions} onEdit={edit} className="span-12" initial={10} />
                )}
              </div>
            )}
            {view === 'money' && <MoneyView state={state} onEdit={edit} onPanel={setPanel} />}
            {view === 'plan' && <PlanView state={state} />}
          </main>
        </FreshContext.Provider>

        {composer && (
          <Composer
            key={composer.editId ?? 'new'}
            state={state}
            open={composer}
            onClose={closeComposer}
            onSaved={(s, message) => {
              const before = new Set(state.transactions.map(t => t.id));
              const ids = s.transactions.filter(t => !before.has(t.id)).map(t => t.id);
              if (composer.editId != null) ids.push(composer.editId);
              setFresh(new Set(ids));
              setState(s);
              closeComposer();
              say(message);
            }}
          />
        )}
        {panel === 'accounts' && <AccountsPanel state={state} onState={setState} onClose={() => setPanel(null)} />}
        {panel === 'settings' && <SettingsPanel state={state} onState={setState} onClose={() => setPanel(null)} />}
        {panel === 'search' && <SearchPanel state={state} onEdit={editFromSearch} onClose={() => setPanel(null)} />}
        {panel === 'recurring' && <RecurringPanel state={state} onState={setState} onToast={say} onClose={() => setPanel(null)} />}
        {toast && (
          <div key={toast.n} className={`toast ${toast.ok ? 'ok' : ''}`} role="status">
            {toast.ok && <Icon name="check" size={16} />}
            {toast.text}
          </div>
        )}
      </div>
    </PrivacyContext.Provider>
  );
}

function quoteLabel(latest: string | null, oldest: string | null): string {
  if (!latest) return '重新整理報價';
  const md = (d: string) => `${Number(d.slice(5, 7))}/${Number(d.slice(8))}`;
  return oldest && oldest !== latest ? `報價 ${md(oldest)}–${md(latest)} 收盤` : `報價 ${md(latest)} 收盤`;
}

function FirstSteps({ onAdd }: { onAdd(): void }) {
  return (
    <section className="card first span-12">
      <header className="card-head">
        <h2>從現在的狀態開始記</h2>
        <button type="button" className="primary" onClick={onAdd}>
          ＋ 記第一筆
        </button>
      </header>
      <ol>
        <li>在「其他 → 存入現金」記下每個帳戶現在有多少錢（勾選「期初」，之後補登以前的收支不會重複計算）</li>
        <li>在「買進」勾選「補登過去買的股票」補上手上的持股，日期選當初買進那天（不會再扣現金）</li>
        <li>之後每筆花費、收入、交易都按右上角「＋ 記一筆」</li>
      </ol>
    </section>
  );
}
