import { createContext, useContext, useEffect, useState } from 'react';
import { useReducedMotion } from './motion';

export const PrivacyContext = createContext(false);

/** A money string, masked while privacy mode is on. Percentages are left alone by callers. */
export function Money({ value, className }: { value: string | null | undefined; className?: string }) {
  const hidden = useContext(PrivacyContext);
  if (value == null) return null;
  return <span className={className}>{hidden ? value.replace(/[\d,.]+/, '••••') : value}</span>;
}

// The last number each rolling figure showed, so it rolls on from there after a remount.
const shown = new Map<string, number>();
const SPLIT = /^([^\d]*)([\d,]+(?:\.(\d+))?)(.*)$/;

/** Money for the big figures: rolls from the last shown value to the new one (0 the first time). */
export function RollingMoney({ id, value, className }: { id: string; value: string | null | undefined; className?: string }) {
  const hidden = useContext(PrivacyContext);
  const reduce = useReducedMotion();
  const m = value == null ? null : SPLIT.exec(value);
  const target = m ? Number(m[2].replace(/,/g, '')) : null;
  const still = hidden || reduce || target == null;
  const [n, setN] = useState(() => (still ? target : (shown.get(id) ?? 0)));

  useEffect(() => {
    if (target == null) return;
    const from = shown.get(id) ?? 0;
    if (still || from === target) {
      shown.set(id, target);
      setN(target);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / 450);
      const v = from + (target - from) * (1 - (1 - p) ** 3);
      shown.set(id, v);
      setN(v);
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [id, target, still]);

  if (value == null) return null;
  if (hidden || !m || n == null || n === target) return <Money className={className} value={value} />;
  const digits = m[3]?.length ?? 0;
  const text = n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return (
    <span className={className}>
      <span aria-hidden>
        {m[1]}
        {text}
        {m[4]}
      </span>
      <span className="visually-hidden">{value}</span>
    </span>
  );
}

export function signClass(sign: number): string {
  return sign > 0 ? 'up' : sign < 0 ? 'down' : '';
}
