import { useState } from 'react';
import { api } from '../api';
import { Money } from '../lib/privacy';
import type { LifePlan, LifePlanInput, Plan, State } from '../types';

type Take = (r: { ok: true; plan: Plan } | { ok: false; error: string }) => void;

const KINDS: [LifePlanInput['kind'], string][] = [
  ['house', '買房'],
  ['car', '買車'],
  ['other', '其他大筆支出'],
];

// Nothing is preset: every number starts empty and only what is filled in gets calculated.
const EMPTY: LifePlanInput = {
  kind: 'house',
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
  account_ids: [],
  active: true,
};

const ym = (m: string) => `${m.slice(0, 4)}/${Number(m.slice(5))}`;

/** 人生計劃: big purchases with their down payment progress and loan; feeds the FIRE projection. */
export function LifePlans({ plan, state, onPlan }: { plan: Plan; state: State; onPlan: Take }) {
  const [editing, setEditing] = useState<LifePlanInput | null>(null);
  const plans = plan.life_plans;
  return (
    <section className="card span-12" aria-labelledby="life-h">
      <header className="card-head">
        <h2 id="life-h">人生計劃</h2>
        {!editing && (
          <button type="button" className="quiet" onClick={() => setEditing(EMPTY)}>
            新增計劃
          </button>
        )}
      </header>
      {plans.length === 0 && !editing && (
        <p className="muted">
          買房、買車或其他大筆支出。只要填價格就能開始，其他像目標年月、頭期款、貸款，知道了再補；填了目標年月的計劃會放進下面的退休試算。
        </p>
      )}
      {plans.length > 0 && (
        <div className="table life-t">
          <div className="thead" aria-hidden>
            <span>計劃</span>
            <span>頭期款與費用</span>
            <span className="hide-sm">每月要存</span>
            <span>貸款月付</span>
          </div>
          {plans.map(p => (
            <PlanRow key={p.id} p={p} onEdit={() => setEditing(p.input)} />
          ))}
        </div>
      )}
      {editing && (
        <LifePlanForm
          key={editing.id ?? 'new'}
          initial={editing}
          accounts={state.accounts.filter(a => !a.archived)}
          onCancel={() => setEditing(null)}
          onSave={async p => {
            const r = await api.saveLifePlan(p);
            onPlan(r);
            if (r.ok) setEditing(null);
          }}
          onDelete={
            editing.id != null
              ? async () => {
                  const r = await api.deleteLifePlan(editing.id!);
                  onPlan(r);
                  if (r.ok) setEditing(null);
                }
              : undefined
          }
        />
      )}
    </section>
  );
}

function PlanRow({ p, onEdit }: { p: LifePlan; onEdit(): void }) {
  return (
    <button type="button" className={`trow ${p.active ? '' : 'archived'}`} onClick={onEdit}>
      <span className="cell">
        <span className="main">
          <span className={`kind-tag kind-${p.kind}`}>{p.kind_label}</span>
          <span className="ellipsis">{p.name}</span>
        </span>
        <span className="sub ellipsis">
          {p.target_month ? ym(p.target_month) : '還沒定時間'}
          {'　價格 '}
          <Money className="num" value={p.price} />
          {!p.active && '　不納入試算'}
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
          <span>已備妥</span>
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
            <span className="sub">{p.target_month ? '已到時間' : '填目標年月才算'}</span>
          </>
        )}
      </span>
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
          <span className="muted small">{p.input.down_ratio === '' ? '全額自付' : '貸款資料未填'}</span>
        )}
      </span>
    </button>
  );
}

function LifePlanForm(props: {
  initial: LifePlanInput;
  accounts: State['accounts'];
  onSave(p: LifePlanInput): void;
  onCancel(): void;
  onDelete?: () => void;
}) {
  const [p, setP] = useState(props.initial);
  const set = (k: keyof LifePlanInput) => (e: React.ChangeEvent<HTMLInputElement>) => setP({ ...p, [k]: e.target.value });
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
      <div className="seg" role="radiogroup" aria-label="類型">
        {KINDS.map(([k, label]) => (
          <button key={k} type="button" role="radio" aria-checked={p.kind === k} className={p.kind === k ? 'on' : ''} onClick={() => setP({ ...p, kind: k })}>
            {label}
          </button>
        ))}
      </div>
      <div className="form-row">
        <label>
          名稱
          <input value={p.name} autoFocus onChange={set('name')} />
        </label>
        <label>
          價格（今天的台幣）
          <input value={p.price} inputMode="decimal" onChange={set('price')} />
        </label>
        <label>
          目標年月（可不填）
          <input type="month" value={p.target_month} onChange={set('target_month')} />
        </label>
      </div>
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
      <fieldset className="checks">
        <legend>頭期款存在哪些帳戶（不選＝總資產）</legend>
        {props.accounts.map(a => (
          <label key={a.id} className="check">
            <input type="checkbox" checked={p.account_ids.includes(a.id)} onChange={() => toggle(a.id)} />
            {a.name}
          </label>
        ))}
      </fieldset>
      <label className="check">
        <input type="checkbox" checked={p.active} onChange={e => setP({ ...p, active: e.target.checked })} />
        納入退休試算和健檢
      </label>
      <div className="actions">
        <button type="submit" className="primary">
          {p.id != null ? '儲存計劃' : '建立計劃'}
        </button>
        <button type="button" className="quiet" onClick={props.onCancel}>
          取消
        </button>
        {props.onDelete && (
          <button type="button" className="quiet danger" onClick={props.onDelete}>
            刪除計劃
          </button>
        )}
      </div>
    </form>
  );
}
