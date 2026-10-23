import { useContext, useEffect, useState } from 'react';
import { api } from '../api';
import { Money, PrivacyContext, Trend } from '../lib/privacy';
import type { Plan, PlanParams, State } from '../types';
import { LineChart } from './Charts';
import { LifePlans } from './LifePlans';
import { HelpTip } from './Panels';

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
      {/* goals and plans right above the projection they feed; 目標配置 kept small beside them (2026-10-23) */}
      <LifePlans plan={plan} state={state} onPlan={take} className="span-8" />
      <Rebalance plan={plan} onPlan={take} />
      <Fire plan={plan} onPlan={take} />
    </div>
  );
}

type Take = (r: { ok: true; plan: Plan } | { ok: false; error: string }) => void;

const MIX_TONES = ['var(--tone-indigo)', 'var(--tone-sky)', 'var(--tone-teal)', 'var(--tone-plum)', 'var(--tone-sand)'];

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
    <section className="card stretch span-4" aria-labelledby="rb-h">
      <header className="card-head">
        <h2 id="rb-h">目標配置</h2>
        <HelpTip label="目標配置說明">
          改目標比例後按 Enter，會自動換算成加總 100%。股票＝債券 ETF 以外的持股；現金含所有帳戶的現金和定存。
        </HelpTip>
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
                    {r[k] >= 0.2 ? `${r.label} ${Math.round(r[k] * 100)}%` : ''}
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
          <span className="r">目標</span>
          <span className="r">要調整</span>
        </div>
        {plan.rebalance.map(r => (
          <div key={r.label} className="trow">
            <span className="cell">
              <span className="main">{r.label}</span>
              <span className="sub num">{Math.round(r.current * 100)}%</span>
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
                <>
                  <Money className="num" value={r.trade.replace(/^[+−]/, '')} />
                  <span className="sub trend-line">
                    <Trend sign={r.trade_sign} />
                    {r.trade_sign > 0 ? '買進' : '賣出'}
                  </span>
                </>
              )}
            </span>
          </div>
        ))}
      </div>
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
                    { name: '含計劃', values: shownPlans.map(p => p.value), style: 'main' },
                    { name: '不含計劃', values: shown.map(p => p.value), style: 'quiet' },
                  ]
                : [{ name: '預估資產', values: shown.map(p => p.value), style: 'main' }]
            }
            target={{ value: wp?.target_raw ?? f.target_raw ?? 0, label: '目標' }}
            marks={wp?.marks.map(m => ({ x: m.year, label: m.name }))}
          />
          <p className="note">
            以今天的購買力計算：報酬先扣掉通膨，每月投入固定不變。
            {wp && '計劃：當月扣掉頭期款與一次性費用，之後每月投入扣掉貸款月付和持有成本；自住房屋不算進可提領的資產。'}
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
