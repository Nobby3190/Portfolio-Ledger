import { useContext, useEffect, useState } from 'react';
import { api, type GoalInput, type GoalScope } from '../api';
import { Money, PrivacyContext, signClass, Trend } from '../lib/privacy';
import type { BacktestResult, Plan, PlanParams, State } from '../types';
import { LineChart } from './Charts';
import { LifePlans } from './LifePlans';
import { WatchlistCard } from './Watchlist';

export function PlanView({ state }: { state: State }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void api.plan().then(r => {
      if (!live) return;
      if (r.ok) setPlan(r.plan);
      else setError(r.error);
    });
    return () => {
      live = false;
    };
  }, [state]);

  const take = (r: { ok: true; plan: Plan } | { ok: false; error: string }) => {
    if (r.ok) {
      setPlan(r.plan);
      setError(null);
    } else setError(r.error);
  };

  if (!plan) return error ? <p className="message bad">{error}</p> : null;
  return (
    <div className="grid">
      {error && <p className="message bad span-12">{error}</p>}
      <WatchlistCard state={state} />
      <Goals plan={plan} state={state} onPlan={take} />
      <Rebalance plan={plan} onPlan={take} />
      {/* right above the projection it feeds */}
      <LifePlans plan={plan} state={state} onPlan={take} />
      <Fire plan={plan} onPlan={take} />
      <BacktestBlock />
    </div>
  );
}

type Take = (r: { ok: true; plan: Plan } | { ok: false; error: string }) => void;

// ── 儲蓄目標 ─────────────────────────────────────────────────────────

const RING = 2 * Math.PI * 40;
const GOAL_TONES = ['var(--hue-teal)', 'var(--hue-sand)', 'var(--hue-sky)', 'var(--hue-plum)', 'var(--hue-indigo)'];
const MIX_TONES = ['var(--tone-indigo)', 'var(--tone-sky)', 'var(--tone-teal)', 'var(--tone-plum)', 'var(--tone-sand)'];

function Goals({ plan, state, onPlan }: { plan: Plan; state: State; onPlan: Take }) {
  const [editing, setEditing] = useState<GoalInput | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const empty: GoalInput = { name: '', target: '', deadline: '', scope: 'cash', account_ids: [] };
  // Errors stay in the form, next to the button: at the top of the page they went unseen and the
  // form looked stuck (2026-10-13).
  const run = async (call: () => Promise<{ ok: true; plan: Plan } | { ok: false; error: string }>) => {
    setSaving(true);
    const r = await call();
    setSaving(false);
    if (!r.ok) return setFormError(r.error);
    onPlan(r);
    setFormError(null);
    setEditing(null);
  };
  return (
    <section className="card stretch span-6" aria-labelledby="goals-h">
      <header className="card-head">
        <h2 id="goals-h">儲蓄目標</h2>
        {!editing && (
          <button type="button" className="quiet" onClick={() => (setFormError(null), setEditing(empty))}>
            新增目標
          </button>
        )}
      </header>
      {plan.goals.length === 0 && !editing && (
        <p className="muted">例如「緊急預備金 30 萬」或「買房頭期款 300 萬，2030 年前」。可以選要算現金、現金＋定存、總資產，或自己挑帳戶。</p>
      )}
      {plan.goals.length > 0 && (
        // 大膽版: one progress ring per goal, coloured in turn; click to edit
        <div className="goal-rings">
          {plan.goals.map((g, i) => (
            <button
              key={g.id}
              type="button"
              className="goal-ring"
              style={{ '--t': GOAL_TONES[i % GOAL_TONES.length] } as React.CSSProperties}
              onClick={() => (setFormError(null), setEditing({ id: g.id, name: g.name, target: g.target_raw, deadline: g.deadline ?? '', scope: g.scope, account_ids: g.account_ids }))}
            >
              <span className="ring">
                <svg viewBox="0 0 100 100" aria-hidden>
                  <circle className="track" cx="50" cy="50" r="40" />
                  <circle className="fill" cx="50" cy="50" r="40" strokeDasharray={`${RING * Math.min(g.ratio, 1)} ${RING}`} transform="rotate(-90 50 50)" />
                </svg>
                <span className="num">{Math.round(g.ratio * 100)}%</span>
              </span>
              <span className="goal-name ellipsis">{g.name}</span>
              <span className="sub num">
                <Money value={g.current} /> / <Money value={g.target} />
              </span>
              <span className="sub ellipsis">
                {g.scope === 'accounts' ? g.accounts.join('、') : g.scope_label}
                {g.deadline && `・${g.deadline} 前`}
              </span>
              {g.done ? (
                <span className="sub strong">已達成</span>
              ) : g.overdue ? (
                <span className="sub warn">已過期限</span>
              ) : g.per_month ? (
                <span className="sub">
                  每月存 <Money className="num" value={g.per_month} />
                </span>
              ) : (
                <span className="sub">
                  還差 <Money className="num" value={g.left} />
                </span>
              )}
            </button>
          ))}
        </div>
      )}
      {editing && (
        <GoalForm
          key={editing.id ?? 'new'}
          initial={editing}
          accounts={state.accounts.filter(a => !a.archived)}
          error={formError}
          saving={saving}
          onCancel={() => setEditing(null)}
          onSave={g => run(() => api.saveGoal(g))}
          onDelete={editing.id != null ? () => run(() => api.deleteGoal(editing.id!)) : undefined}
        />
      )}
    </section>
  );
}

const SCOPES: [GoalScope, string, string][] = [
  ['cash', '現金與活存', '台幣的銀行、現金帳戶，加上證券帳戶裡的交割款（不含股票）；新開的帳戶會自動算進去。適合緊急預備金'],
  ['cash_deposit', '現金＋定存', '現金與活存，再加上台幣定存'],
  ['total', '總資產', '和首頁的總資產一樣：含股票，扣掉信用卡和貸款'],
  ['accounts', '自訂帳戶', '自己勾帳戶；外幣存款要算進去時用這個'],
];

function GoalForm(props: {
  initial: GoalInput;
  accounts: State['accounts'];
  error: string | null;
  saving: boolean;
  onSave(g: GoalInput): void;
  onCancel(): void;
  onDelete?: () => void;
}) {
  const [g, setG] = useState(props.initial);
  const toggle = (id: number) =>
    setG({ ...g, account_ids: g.account_ids.includes(id) ? g.account_ids.filter(x => x !== id) : [...g.account_ids, id] });
  return (
    <form
      className="form inline-form"
      onSubmit={e => {
        e.preventDefault();
        props.onSave(g);
      }}
    >
      <div className="form-row">
        <label>
          名稱
          <input value={g.name} autoFocus onChange={e => setG({ ...g, name: e.target.value })} placeholder="緊急預備金" />
        </label>
        <label>
          目標金額（台幣）
          <input value={g.target} inputMode="decimal" onChange={e => setG({ ...g, target: e.target.value })} placeholder="300000 或 30萬" />
        </label>
        <label>
          期限（可不填）
          <input type="date" value={g.deadline} onChange={e => setG({ ...g, deadline: e.target.value })} />
        </label>
      </div>
      <div className="field">
        <span className="field-label">追蹤範圍</span>
        <div className="seg" role="radiogroup" aria-label="追蹤範圍">
          {SCOPES.map(([k, label]) => (
            <button key={k} type="button" role="radio" aria-checked={g.scope === k} className={g.scope === k ? 'on' : ''} onClick={() => setG({ ...g, scope: k })}>
              {label}
            </button>
          ))}
        </div>
        <small className="muted">{SCOPES.find(([k]) => k === g.scope)?.[2]}</small>
      </div>
      {g.scope === 'accounts' && (
        <fieldset className="checks">
          <legend>追蹤哪些帳戶（帳戶的金額＝現金＋持股市值）</legend>
          {props.accounts.map(a => (
            <label key={a.id} className="check">
              <input type="checkbox" checked={g.account_ids.includes(a.id)} onChange={() => toggle(a.id)} />
              {a.name}
            </label>
          ))}
        </fieldset>
      )}
      {props.error && <p className="message bad">{props.error}</p>}
      <div className="actions">
        <button type="submit" className="primary" disabled={props.saving}>
          {props.saving ? '儲存中…' : g.id != null ? '儲存目標' : '建立目標'}
        </button>
        <button type="button" className="quiet" onClick={props.onCancel}>
          取消
        </button>
        {props.onDelete && (
          <button type="button" className="quiet danger" onClick={props.onDelete}>
            刪除目標
          </button>
        )}
      </div>
    </form>
  );
}

// ── 再平衡 ───────────────────────────────────────────────────────────

function Rebalance({ plan, onPlan }: { plan: Plan; onPlan: Take }) {
  const [targets, setTargets] = useState<Record<string, string>>(() =>
    Object.fromEntries(plan.rebalance.map(r => [r.label, String(r.target_raw)])),
  );
  useEffect(() => {
    setTargets(Object.fromEntries(plan.rebalance.map(r => [r.label, String(r.target_raw)])));
  }, [plan]);
  const save = async () => onPlan(await api.saveTargets(targets));

  return (
    <section className="card stretch span-6" aria-labelledby="rb-h">
      <header className="card-head">
        <h2 id="rb-h">目標配置</h2>
        <span className="aside">改目標比例後按 Enter</span>
      </header>
      {/* 大膽版: now and target as two stacked bars on the same colours */}
      <div className="mix">
        {(['current', 'target'] as const).map(k => (
          <div key={k} className="mix-row">
            <span className="muted small">{k === 'current' ? '目前' : '目標'}</span>
            <span className="mix-bar" role="img" aria-label={plan.rebalance.map(r => `${r.label} ${Math.round(r[k] * 100)}%`).join('，')}>
              {plan.rebalance.map((r, i) =>
                r[k] > 0 ? (
                  <span key={r.label} style={{ flexGrow: r[k], background: MIX_TONES[i % MIX_TONES.length] }}>
                    {r[k] >= 0.12 ? `${r.label} ${Math.round(r[k] * 100)}%` : ''}
                  </span>
                ) : null,
              )}
            </span>
          </div>
        ))}
      </div>
      <div className="table rebalance-t">
        <div className="thead" aria-hidden>
          <span>類別</span>
          <span>目前（線）／目標（刻度）</span>
          <span>目標</span>
          <span>要調整</span>
        </div>
        {plan.rebalance.map(r => (
          <div key={r.label} className="trow">
            <span>{r.label}</span>
            <span className="share-cell">
              <span className="num small">{Math.round(r.current * 100)}%</span>
              <span className="share-meter" aria-hidden>
                <span style={{ width: `${Math.min(r.current, 1) * 100}%` }} />
                <i style={{ left: `${r.target * 100}%` }} />
              </span>
            </span>
            <span className="cell r">
              <span>
                <input
                  className="inline-input pct-input num"
                  inputMode="decimal"
                  aria-label={`${r.label}目標比例`}
                  value={targets[r.label] ?? ''}
                  onChange={e => setTargets({ ...targets, [r.label]: e.target.value })}
                  onBlur={save}
                  onKeyDown={e => e.key === 'Enter' && save()}
                />{' '}
                %
              </span>
            </span>
            <span className="cell r">
              {r.trade_sign === 0 ? (
                <span className="muted">剛好</span>
              ) : (
                <span className="trend-line">
                  <Trend sign={r.trade_sign} />
                  {r.trade_sign > 0 ? '買進' : '賣出'}
                  <Money className="num" value={r.trade.replace(/^[+−]/, '')} />
                </span>
              )}
            </span>
          </div>
        ))}
      </div>
      <p className="note">股票＝債券 ETF 以外的持股；現金含所有帳戶的現金和定存。目標比例會自動換算成加總 100%。</p>
    </section>
  );
}

// ── 退休／FIRE ───────────────────────────────────────────────────────

const FIRE_FIELDS: { key: keyof PlanParams; label: string; unit: string; auto?: 'current' | 'monthly' | 'spend' }[] = [
  { key: 'current', label: '目前資產', unit: '元', auto: 'current' },
  { key: 'monthly', label: '每月投入', unit: '元', auto: 'monthly' },
  { key: 'spend', label: '退休後每年支出', unit: '元', auto: 'spend' },
  { key: 'return', label: '預期年報酬', unit: '%' },
  { key: 'inflation', label: '通膨', unit: '%' },
  { key: 'withdrawal', label: '每年提領率', unit: '%' },
];

function Fire({ plan, onPlan }: { plan: Plan; onPlan: Take }) {
  const hidden = useContext(PrivacyContext);
  const f = plan.fire;
  const [params, setParams] = useState<PlanParams>(f.params);
  useEffect(() => setParams(f.params), [f.params]);
  const save = async () => onPlan(await api.savePlan(params));
  const thisYear = new Date().getFullYear();
  // Show a few years past the finish line, not always the full 50-year horizon.
  const wp = f.with_plans;
  const last = Math.max(f.years ?? 0, wp?.years ?? 0, ...(wp?.marks.map(m => m.year) ?? []));
  const years = f.years != null || wp?.years != null ? Math.min(50, Math.max(10, Math.ceil(last) + 5)) : 30;
  const shown = (f.series ?? []).slice(0, years + 1);
  const shownPlans = wp?.series.slice(0, years + 1);

  return (
    <section className="card span-12" aria-labelledby="fire-h">
      <header className="card-head">
        <h2 id="fire-h">退休試算</h2>
        <span className="aside">空白的欄位會自動帶入你的資料</span>
      </header>
      <form
        className="fire-form"
        onSubmit={e => {
          e.preventDefault();
          void save();
        }}
      >
        {FIRE_FIELDS.map(fd => {
          // The money fields (the ones with an automatic value) are masked and locked in privacy mode.
          const masked = hidden && fd.auto != null;
          return (
            <label key={fd.key}>
              <span className="muted small">{fd.label}</span>
              <span className="unit-input">
                <input
                  className="num"
                  inputMode="decimal"
                  value={masked ? (params[fd.key] ? '••••' : '') : params[fd.key]}
                  placeholder={masked ? '••••' : fd.auto ? Number(f.auto[fd.auto]).toLocaleString('en-US') : ''}
                  readOnly={masked}
                  title={masked ? '隱藏金額中，關掉後才能修改' : undefined}
                  onChange={e => setParams({ ...params, [fd.key]: e.target.value })}
                  onBlur={masked ? undefined : save}
                />
                <span className="muted">{fd.unit}</span>
              </span>
              {fd.auto && params[fd.key] === '' && <span className="muted tiny">自動：{autoNote(fd.auto, f.months_of_data)}</span>}
            </label>
          );
        })}
      </form>

      {!f.ready ? (
        <p className="muted">填入退休後每年支出，或先記幾個月的支出，就能算出需要多少錢。</p>
      ) : (
        <>
          <p className="answer">
            需要 <Money className="num strong" value={f.target} />
            <span className="muted">（每年支出 ÷ 提領率）</span>，
            {f.reached_now ? (
              <>已經達到了。</>
            ) : f.years != null ? (
              <>
                照這個速度大約 <b className="num">{f.years}</b> 年後、<b className="num">{f.year}</b> 年達標。
              </>
            ) : (
              <>50 年內達不到，試著提高每月投入或降低支出。</>
            )}
            {wp && (
              <>
                <br />
                納入{wp.names.join('、')}後，需要 <Money className="num strong" value={wp.target} />，
                {wp.year == null ? (
                  <>50 年內達不到。</>
                ) : f.year == null || wp.delay_years == null ? (
                  <>
                    大約 <b className="num">{wp.year}</b> 年達標。
                  </>
                ) : wp.delay_years > 0 ? (
                  <>
                    從 <b className="num">{f.year}</b> 年延到 <b className="num">{wp.year}</b> 年（
                    <b className="num">+{wp.delay_years}</b> 年）。
                  </>
                ) : (
                  <>
                    一樣在 <b className="num">{wp.year}</b> 年達標。
                  </>
                )}
              </>
            )}
          </p>
          <LineChart
            ariaLabel="資產成長預估（以今天的購買力）"
            labels={shown.map(p => (p.year === 0 ? '今年' : `${thisYear + p.year}`))}
            series={
              shownPlans
                ? [
                    { name: '含人生計劃', values: shownPlans.map(p => p.value), style: 'main' },
                    { name: '不含計劃', values: shown.map(p => p.value), style: 'quiet' },
                  ]
                : [{ name: '預估資產', values: shown.map(p => p.value), style: 'main' }]
            }
            target={{ value: wp?.target_raw ?? f.target_raw ?? 0, label: '目標' }}
            marks={wp?.marks.map(m => ({ x: m.year, label: m.name }))}
          />
          <p className="note">
            以今天的購買力計算：報酬先扣掉通膨，每月投入固定不變。
            {wp && '人生計劃：當月扣掉頭期款與一次性費用，之後每月投入扣掉貸款月付和持有成本；自住房屋不算進可提領的資產。'}
            只是估算，不是保證。
          </p>
        </>
      )}
    </section>
  );
}

function autoNote(key: 'current' | 'monthly' | 'spend', months: number): string {
  if (key === 'current') return '總資產';
  if (months === 0) return '還沒有收支紀錄';
  return key === 'monthly' ? `近 ${Math.min(months, 6)} 個月平均結餘` : `近 ${months} 個月支出換算成一年`;
}

// ── 定期定額回測 ─────────────────────────────────────────────────────

function BacktestBlock() {
  const [symbol, setSymbol] = useState('0050');
  const [start, setStart] = useState(`${new Date().getFullYear() - 10}-01`);
  const [amount, setAmount] = useState('5000');
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    const r = await api.backtest(symbol, start, amount);
    setBusy(false);
    if (r.ok) {
      setResult(r.result);
      setError(null);
    } else setError(r.error);
  }

  return (
    <section className="card span-12" aria-labelledby="bt-h">
      <header className="card-head">
        <h2 id="bt-h">定期定額回測</h2>
        <span className="aside">如果當初每月固定買，現在會有多少</span>
      </header>
      <form
        className="bt-form"
        onSubmit={e => {
          e.preventDefault();
          void run();
        }}
      >
        <label>
          <span className="muted small">代號</span>
          <input value={symbol} onChange={e => setSymbol(e.target.value)} />
        </label>
        <label>
          <span className="muted small">從</span>
          <input type="month" value={start} onChange={e => setStart(e.target.value)} />
        </label>
        <label>
          <span className="muted small">每月</span>
          <input className="num" inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)} />
        </label>
        <button type="submit" className="primary" disabled={busy}>
          {busy ? '計算中…' : '回測'}
        </button>
      </form>
      {error && <p className="message bad">{error}</p>}
      {result && (
        <>
          <p className="answer">
            {result.name}：從 {result.from} 起 {result.months} 個月，投入 <Money className="num" value={result.invested} />，現在值{' '}
            <Money className="num strong" value={result.value} /> {result.currency !== 'TWD' && result.currency}，
            <span className={signClass(result.gain_sign)}>
              <Trend sign={result.gain_sign} />
              <Money className="num" value={result.gain} />（{result.return_pct}）
            </span>
            {result.xirr && <>，年化 {result.xirr}</>}。
          </p>
          <LineChart
            ariaLabel={`${result.symbol} 定期定額：投入與市值`}
            labels={result.series.map(p => p.month.replace('-', '/'))}
            series={[
              { name: '累計投入', values: result.series.map(p => p.invested), style: 'quiet' },
              { name: '市值', values: result.series.map(p => p.value), style: 'main' },
            ]}
          />
          <p className="note">用 Yahoo 月線的還原收盤價（股利再投入），每月以當月收盤價買進，不含手續費。</p>
        </>
      )}
    </section>
  );
}
