import { Fragment, useState } from 'react';
import { api } from '../api';
import { Money } from '../lib/privacy';
import type { LifePlan, LifePlanInput, Plan, PlanScope, State } from '../types';
import { HelpTip } from './Panels';

type Take = (r: { ok: true; plan: Plan } | { ok: false; error: string }) => void;

// Nothing is preset: every number starts empty and only what is filled in gets calculated. The user
// names the plan; there is no house/car type to pick any more (2026-10-13), new plans are 'other'.
// 儲蓄目標 were merged in (2026-10-23): a goal is a plan without the big-purchase details, kept out of
// the projection until the user turns it on.
const EMPTY: LifePlanInput = {
  kind: 'other',
  name: '',
  target_month: '',
  price: '',
  down_ratio: '',
  one_off: '',
  loan_rate: '',
  loan_years: '',
  grace_years: '',
  monthly_cost: '',
  rent_saved: '',
  scope: 'cash',
  account_ids: [],
  active: false,
};

const DETAILS: (keyof LifePlanInput)[] = ['down_ratio', 'one_off', 'loan_rate', 'loan_years', 'grace_years', 'monthly_cost', 'rent_saved'];

const SCOPES: [PlanScope, string, string][] = [
  ['cash', '現金與活存', '台幣的銀行、現金帳戶，加上證券帳戶裡的交割款（不含股票）；新開的帳戶會自動算進去。適合緊急預備金。'],
  ['cash_deposit', '現金＋定存', '現金與活存，再加上台幣定存。'],
  ['total', '總資產', '含股票，扣掉信用卡和貸款；和其他選「總資產」的項目共用，依目標年月先後分配，同一筆錢不會算兩次。'],
  ['accounts', '自訂帳戶', '自己勾帳戶，帳戶的金額＝現金＋持股市值；外幣存款要算進去時用這個。'],
];

const ym = (m: string) => `${m.slice(0, 4)}/${Number(m.slice(5))}`;

/** 目標與計劃: savings goals and big purchases, their progress and loans; active ones feed the FIRE projection. */
export function LifePlans({ plan, state, onPlan, className = '' }: { plan: Plan; state: State; onPlan: Take; className?: string }) {
  const [editing, setEditing] = useState<LifePlanInput | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const plans = plan.life_plans;
  const withLoan = plans.some(p => p.loan);
  // Errors stay in the form, next to the button (they used to go to the top of the page).
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
    <section className={`card stretch ${className}`} aria-labelledby="life-h">
      <header className="card-head">
        <h2 id="life-h">目標與計劃</h2>
        {!editing && (
          <button type="button" className="quiet" onClick={() => (setFormError(null), setEditing(EMPTY))}>
            新增
          </button>
        )}
      </header>
      {plans.length === 0 && !editing && (
        <p className="muted">例如「緊急預備金 30 萬」或「買房，2030 年 6 月」。大筆支出可以再填頭期款、貸款，放進下面的退休試算。</p>
      )}
      {plans.length > 0 && (
        <div className={`table life-t${withLoan ? ' with-loan' : ''}`}>
          <div className="thead" aria-hidden>
            <span>目標</span>
            <span>已存／需要</span>
            <span className="hide-sm">每月要存</span>
            {withLoan && <span>貸款月付</span>}
          </div>
          {plans.map(p => (
            <PlanRow key={p.id} p={p} withLoan={withLoan} onEdit={() => (setFormError(null), setEditing(p.input))} />
          ))}
        </div>
      )}
      {editing && (
        <LifePlanForm
          key={editing.id ?? 'new'}
          initial={editing}
          accounts={state.accounts.filter(a => !a.archived || editing.account_ids.includes(a.id))} // a ticked archived one can still be unticked
          error={formError}
          saving={saving}
          onCancel={() => setEditing(null)}
          onSave={p => run(() => api.saveLifePlan(p))}
          onDelete={editing.id != null ? () => run(() => api.deleteLifePlan(editing.id!)) : undefined}
        />
      )}
    </section>
  );
}

function PlanRow({ p, withLoan, onEdit }: { p: LifePlan; withLoan: boolean; onEdit(): void }) {
  return (
    <button type="button" className="trow" onClick={onEdit}>
      <span className="cell">
        <span className="main">
          <span className="ellipsis">{p.name}</span>
        </span>
        <span className="sub ellipsis">
          {p.target_month ? ym(p.target_month) : '沒有期限'}
          {'・'}
          {/* accounts that were deleted since drop out; then say the scope */}
          {p.scope === 'accounts' && p.accounts.length ? p.accounts.join('、') : p.scope_label}
          {p.active && '・納入試算'}
        </span>
      </span>
      <span className="cell r">
        <span>
          <Money className="num" value={p.saved} />
          <span className="muted"> / </span>
          <Money className="num" value={p.need} />
        </span>
        <span className="bar-cell" style={{ width: '100%' }}>
          <span className="meter" aria-hidden>
            <span style={{ width: `${p.ratio * 100}%` }} />
          </span>
          <span className="num small">{Math.round(p.ratio * 100)}%</span>
        </span>
      </span>
      <span className="cell r hide-sm">
        {!p.left ? (
          <span className="strong">已達成</span>
        ) : p.per_month ? (
          <>
            <Money className="num" value={p.per_month} />
            <span className="sub">
              還差 <Money className="num" value={p.left} />
            </span>
          </>
        ) : (
          <>
            <Money className="num" value={p.left} />
            <span className={`sub${p.overdue ? ' warn' : ''}`}>{p.overdue ? '已過期限' : '還差'}</span>
          </>
        )}
      </span>
      {withLoan && (
        <span className="cell r">
          {p.loan ? (
            <>
              <Money className="num" value={p.loan.payment} />
              {p.loan.grace_payment && (
                <span className="sub">
                  寬限期 <Money className="num" value={p.loan.grace_payment} />
                </span>
              )}
              {p.burden != null && (
                <span className={`sub lv-${p.burden_level}`}>
                  <i className="lv-dot" aria-hidden />
                  佔收入 {Math.round(p.burden * 100)}%
                </span>
              )}
            </>
          ) : (
            <span className="muted small">—</span>
          )}
        </span>
      )}
    </button>
  );
}

function LifePlanForm(props: {
  initial: LifePlanInput;
  accounts: State['accounts'];
  error: string | null;
  saving: boolean;
  onSave(p: LifePlanInput): void;
  onCancel(): void;
  onDelete?: () => void;
}) {
  const [p, setP] = useState(props.initial);
  // A new plan with a down payment or a loan is a big purchase: turn 納入試算 on, until the user sets it.
  const [activeSet, setActiveSet] = useState(props.initial.id != null);
  const set = (k: keyof LifePlanInput) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const next = { ...p, [k]: e.target.value };
    if (!activeSet && DETAILS.includes(k)) next.active = DETAILS.some(d => next[d] !== '');
    setP(next);
  };
  const toggle = (id: number) =>
    setP({ ...p, account_ids: p.account_ids.includes(id) ? p.account_ids.filter(x => x !== id) : [...p.account_ids, id] });
  const num = (k: keyof LifePlanInput, label: string, hint?: string) => (
    <label>
      {label}
      <input value={p[k] as string} inputMode="decimal" onChange={set(k)} placeholder={hint} />
    </label>
  );
  return (
    <form
      className="form inline-form"
      onSubmit={e => {
        e.preventDefault();
        props.onSave(p);
      }}
    >
      <div className="form-row">
        <label>
          名稱
          <input value={p.name} autoFocus onChange={set('name')} placeholder="緊急預備金、買房…" />
        </label>
        {/* not a <label>: the「?」button inside would take the label's clicks */}
        <div className="form-label">
          <span className="field-head">
            <label htmlFor="plan-price">目標金額</label>
            <HelpTip label="目標金額說明">以今天的購買力填。買東西填總價；下面填了頭期款比例，就只算頭期款和一次性費用要存多少。</HelpTip>
          </span>
          <input id="plan-price" value={p.price} inputMode="decimal" onChange={set('price')} placeholder="300000 或 30萬" />
        </div>
        <label>
          目標年月（可不填）
          <input type="month" value={p.target_month} onChange={set('target_month')} />
        </label>
      </div>
      <div className="field">
        <span className="field-head">
          <span className="field-label">追蹤範圍</span>
          <HelpTip label="追蹤範圍說明">
            {SCOPES.map(([k, label, text]) => (
              <Fragment key={k}>
                <b>{label}</b>
                {text}
              </Fragment>
            ))}
          </HelpTip>
        </span>
        <div className="seg" role="radiogroup" aria-label="追蹤範圍">
          {SCOPES.map(([k, label]) => (
            <button key={k} type="button" role="radio" aria-checked={p.scope === k} className={p.scope === k ? 'on' : ''} onClick={() => setP({ ...p, scope: k })}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {p.scope === 'accounts' && (
        <fieldset className="checks">
          <legend>追蹤哪些帳戶</legend>
          {props.accounts.map(a => (
            <label key={a.id} className="check">
              <input type="checkbox" checked={p.account_ids.includes(a.id)} onChange={() => toggle(a.id)} />
              {a.name}
            </label>
          ))}
        </fieldset>
      )}
      <details className="plan-details" open={DETAILS.some(d => props.initial[d] !== '')}>
        <summary>大筆支出：頭期款、貸款、持有成本</summary>
        <div className="form-row">
          {num('down_ratio', '頭期款比例 %', '空白＝全額自付')}
          {num('one_off', '一次性費用', '稅費、仲介、裝潢…')}
        </div>
        <div className="form-row">
          {num('loan_rate', '貸款年利率 %')}
          {num('loan_years', '貸款年期')}
          {num('grace_years', '寬限期（年）', '空白＝沒有')}
        </div>
        <div className="form-row">
          {num('monthly_cost', '買了之後每月持有成本', '管理費、保險、油錢…')}
          {num('rent_saved', '買了之後每月省下的房租')}
        </div>
      </details>
      <span className="field-head">
        <label className="check">
          <input type="checkbox" checked={p.active} onChange={e => (setActiveSet(true), setP({ ...p, active: e.target.checked }))} />
          納入退休試算和健檢
        </label>
        <HelpTip label="納入試算說明">
          填了目標年月的項目，會在那個月從退休試算的資產扣掉頭期款和費用，之後每月扣貸款和持有成本。緊急預備金這類不會花掉的錢不用勾。
        </HelpTip>
      </span>
      {props.error && <p className="message bad">{props.error}</p>}
      <div className="actions">
        <button type="submit" className="primary" disabled={props.saving}>
          {props.saving ? '儲存中…' : p.id != null ? '儲存' : '建立'}
        </button>
        <button type="button" className="quiet" onClick={props.onCancel}>
          取消
        </button>
        {props.onDelete && (
          <button type="button" className="quiet danger" onClick={props.onDelete}>
            刪除
          </button>
        )}
      </div>
    </form>
  );
}
