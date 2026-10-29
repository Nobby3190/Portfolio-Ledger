import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import { Activity } from './components/Activity';
import { AdviceButton } from './components/Advice';
import { AlertsButton } from './components/Alerts';
import { RecurringPanel, SearchPanel } from './components/Bookkeeping';
import { Composer, type ComposerOpen } from './components/Composer';
import { DepositsFx } from './components/DepositsFx';
import { DividendsCard, DividendsTile } from './components/Dividends';
import { Holdings } from './components/Holdings';
import { LoansCard } from './components/Loans';
import { MoneyView } from './components/MoneyView';
import { AccountsPanel, CategoriesPanel, SettingsPanel } from './components/Panels';
import { PlanView } from './components/PlanView';
import { AllocationCard, NetWorthCard } from './components/Summary';
import { WatchlistCard } from './components/Watchlist';
import { BrandMark, Icon, type IconName, setCategoryColors } from './lib/icons';
import { accountColor } from './lib/institutions';
import { FreshContext } from './lib/motion';
import { Money, PrivacyContext } from './lib/privacy';
import type { State } from './types';

const RAIL_TYPES = ['broker_tw', 'broker_us', 'bank', 'deposit'];
type Panel = 'accounts' | 'settings' | 'search' | 'recurring' | 'categories' | null;
type View = 'assets' | 'money' | 'plan';
const VIEWS: [View, string, IconName][] = [
  ['assets', '資產', 'chart'],
  ['money', '收支', 'wallet'],
  ['plan', '規劃', 'flag'],
];

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>(null);
  const [view, setViewState] = useState<View>('assets');
  const [composer, setComposer] = useState<ComposerOpen | null>(null);
  const [back, setBack] = useState<Panel>(null); // the panel to return to after editing from it
  const [toast, setToast] = useState<{ text: string; ok: boolean; n: number; action?: { label: string; run(): void } } | null>(null);
  const [fresh, setFresh] = useState<ReadonlySet<number>>(new Set());
  const say = useCallback(
    (text: string, ok = true, action?: { label: string; run(): void }) => setToast(t => ({ text, ok, action, n: (t?.n ?? 0) + 1 })),
    [],
  );

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
    const t = setTimeout(() => setToast(null), toast.action ? 6600 : 2600); // time to reach its button
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

  // 隱藏金額 (2026-10-18): hidden on every launch; showing the amounts takes Touch ID or the login password,
  // and they hide again a minute after switching away, on minimising, or when the screen locks.
  const [hidden, setHidden] = useState(true);
  const lockOn = state?.settings.privacy_lock !== '0';
  const loaded = state != null;
  useEffect(() => {
    if (loaded && !lockOn) setHidden(false); // the lock is turned off: open showing the amounts, like before
  }, [loaded]); // only on the first load; turning it off later doesn't show the amounts by itself
  const unlocking = useRef(false);
  const togglePrivacy = useCallback(async () => {
    if (!hidden) return setHidden(true);
    if (!lockOn) return setHidden(false);
    if (unlocking.current) return;
    unlocking.current = true;
    try {
      const r = await api.unlock();
      if (r.ok) setHidden(false);
      else if (!r.cancelled) say(r.error, false);
    } finally {
      unlocking.current = false;
    }
  }, [hidden, lockOn, say]);
  useEffect(() => {
    if (!lockOn) return;
    let timer: number | undefined;
    const lock = () => setHidden(true);
    const onBlur = () => {
      clearTimeout(timer);
      timer = window.setTimeout(lock, 60_000);
    };
    const onFocus = () => clearTimeout(timer);
    const onVisible = () => document.hidden && lock();
    window.ledgerLock = lock;
    window.addEventListener('blur', onBlur);
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearTimeout(timer);
      window.ledgerLock = undefined;
      window.removeEventListener('blur', onBlur);
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [lockOn]);

  const edit = useCallback(async (id: number) => {
    const r = await api.txFields(id);
    if (r.ok) setComposer({ editId: id, fields: r.fields });
    else say(r.error, false);
    return r.ok;
  }, [say]);

  // Editing a search result: the composer replaces the panel, which comes back when it closes.
  const editFromSearch = useCallback(
    (id: number) => {
      setPanel(null);
      setBack('search');
      void edit(id).then(ok => {
        if (ok) return;
        setBack(null); // no composer opened: nothing will close and bring the search back
        setPanel('search');
      });
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

  setCategoryColors(state.categories); // before the views render their category colours
  const q = state.quotes;

  return (
    <PrivacyContext.Provider value={hidden}>
      <div className={`app up-${state.settings.up_color}`}>
        {/* 大膽版 (2026-10-16): a left rail for the views and accounts replaces the top bar; it folds into a
            top strip on narrow windows. */}
        <div className="shell">
          <aside className="rail">
            <span className="brand" aria-label="帳本 Ledger">
              <BrandMark />
              LEDGER
            </span>
            <nav className="rail-nav" aria-label="視圖">
              {VIEWS.map(([v, label, icon], i) => (
                <button key={v} type="button" className={`rail-view rail-${v} ${view === v ? 'on' : ''}`} aria-current={view === v ? 'page' : undefined} title={`⌘${i + 1}`} onClick={() => setView(v)}>
                  <span className="rail-ic" aria-hidden>
                    <Icon name={icon} size={16} />
                  </span>
                  <span className="rail-label">{label}</span>
                </button>
              ))}
            </nav>
            <div className="rail-accts">
              <button type="button" className="rail-h" onClick={() => setPanel('accounts')}>
                帳戶
                <span aria-hidden>›</span>
              </button>
              {/* investment (券商) and savings (活存、定存) accounts only; cards, cash and loans are in the 帳戶 panel (2026-10-16) */}
              {state.accounts
                .filter(a => !a.archived && RAIL_TYPES.includes(a.type))
                .map(a => (
                  <button key={a.id} type="button" className="rail-acct" style={{ '--c': accountColor(a) } as React.CSSProperties} onClick={() => setPanel('accounts')}>
                    <i aria-hidden />
                    <span className="ellipsis">{a.name}</span>
                    <Money className="num" value={a.value_twd} />
                  </button>
                ))}
            </div>
            <div className="rail-foot">
              <button
                type="button"
                className="quiet status"
                onClick={() => void api.refresh().then(load)}
                title={q.errors.join('\n') || '重新抓報價（⌘R）'}
              >
                {q.running ? '更新報價中…' : q.errors.length ? `報價更新失敗（${q.errors.length}）` : quoteLabel(q.latest, q.oldest)}
              </button>
              <span className="rail-tools">
                <button type="button" className="quiet" onClick={togglePrivacy} aria-pressed={hidden} title={hidden && lockOn ? '⌘⇧H，需要 Touch ID 或密碼' : '⌘⇧H'}>
                  {hidden ? '顯示金額' : '隱藏金額'}
                </button>
                <button type="button" className="quiet rail-acct-btn" onClick={() => setPanel('accounts')}>
                  帳戶
                </button>
                <button type="button" className="quiet" onClick={() => setPanel('settings')} title="⌘,">
                  設定
                </button>
              </span>
              <button type="button" className="primary add" onClick={() => setComposer({ editId: null })} title="⌘K">
                ＋ 記一筆
                <kbd>⌘K</kbd>
              </button>
            </div>
          </aside>

          <div className="main">
          <header className="view-head">
            <h1>{VIEWS.find(([v]) => v === view)![1]}</h1>
            <span className="head-icons">
              <AlertsButton state={state} onToast={text => say(text)} />
              {view === 'assets' && <AdviceButton state={state} />}
            </span>
          </header>
        <FreshContext.Provider value={fresh}>
          <main className="page">
            {state.missing_fx.length > 0 && (
              <p className="message bad span-12">還沒有 {state.missing_fx.join('、')} 匯率，這些帳戶暫時不計入總資產；連上網路後會自動更新。</p>
            )}
            {view === 'assets' && (
              <div className="grid">
                <NetWorthCard state={state} className="span-12" />
                {state.transactions.length === 0 && state.accounts.length > 0 && <FirstSteps onAdd={() => setComposer({ editId: null })} />}
                {/* investments first: tracking them is one of the reasons for the app (2026-10-13) */}
                <Holdings
                  holdings={state.holdings}
                  closed={state.closed}
                  value={state.holdings_value}
                  unrealized={state.holdings_unrealized}
                  unrealizedSign={state.holdings_unrealized_sign}
                  unrealizedPct={state.holdings_unrealized_pct}
                  dayChange={state.day_change}
                  dayChangePct={state.day_change_pct}
                  daySign={state.day_sign}
                  totalReturn={state.total_return}
                  totalReturnPct={state.total_return_pct}
                  returnSign={state.return_sign}
                  xirr={state.xirr}
                  transactions={state.transactions}
                  today={state.today}
                  onEdit={edit}
                  onBuy={() => setComposer({ editId: null, kind: 'buy' })}
                />
                <div className="stack span-4">
                  <DividendsTile state={state} />
                  <AllocationCard state={state} />
                </div>
                {/* 自選股 sits with the holdings: quotes, notes and 財報 like them (moved from 規劃 2026-10-23) */}
                <WatchlistCard state={state} />
                <DividendsCard state={state} />
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
          </div>
        </div>

        {composer && (
          <Composer
            key={composer.editId ?? 'new'}
            state={state}
            open={composer}
            onClose={closeComposer}
            onSaved={(s, message, follow) => {
              const before = new Set(state.transactions.map(t => t.id));
              const ids = s.transactions.filter(t => !before.has(t.id)).map(t => t.id);
              if (composer.editId != null) ids.push(composer.editId);
              setFresh(new Set(ids));
              setState(s);
              closeComposer();
              say(message, true, follow && { label: follow.label, run: () => setComposer(follow.open) });
            }}
          />
        )}
        {panel === 'accounts' && <AccountsPanel state={state} onState={setState} onClose={() => setPanel(null)} />}
        {panel === 'settings' && <SettingsPanel state={state} onState={setState} onClose={() => setPanel(null)} />}
        {panel === 'search' && <SearchPanel state={state} onEdit={editFromSearch} onClose={() => setPanel(null)} />}
        {panel === 'categories' && <CategoriesPanel state={state} onState={setState} onClose={() => setPanel(null)} />}
        {panel === 'recurring' && <RecurringPanel state={state} onState={setState} onToast={say} onClose={() => setPanel(null)} />}
        {toast && (
          <div key={toast.n} className={`toast ${toast.ok ? 'ok' : ''} ${toast.action ? 'has-action' : ''}`} role="status">
            {toast.ok && <Icon name="check" size={16} />}
            {toast.text}
            {toast.action && (
              <button
                type="button"
                className="toast-action"
                onClick={() => {
                  toast.action?.run();
                  setToast(null);
                }}
              >
                {toast.action.label}
              </button>
            )}
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
        <li>用「買進 → 補登」補上手上的持股，日期選當初買進那天（不會再扣現金）</li>
        <li>之後每筆花費、收入、交易都按右上角「＋ 記一筆」</li>
      </ol>
    </section>
  );
}
