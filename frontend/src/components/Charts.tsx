import { useContext, useId, useLayoutEffect, useRef, useState } from 'react';
import { PrivacyContext } from '../lib/privacy';

// Series are told apart by weight and dash (plus a legend): the main series is the brand blue,
// the quiet one a lighter dashed tone. Red/green stay reserved for up/down.

/** 1,234 / 12.3萬 / 1.2億 — axis labels and tooltips for big TWD-ish numbers. */
export function compact(n: number): string {
  const a = Math.abs(n);
  const sign = n < 0 ? '−' : '';
  if (a >= 1e8) return `${sign}${(a / 1e8).toFixed(a >= 1e9 ? 0 : 1)}億`;
  if (a >= 1e4) return `${sign}${(a / 1e4).toLocaleString('en-US', { maximumFractionDigits: a >= 1e6 ? 0 : 1 })}萬`;
  return `${sign}${Math.round(a).toLocaleString('en-US')}`;
}

interface Series {
  name: string;
  values: number[];
  style: 'main' | 'quiet'; // main: solid ink, quiet: dashed lighter ink
}

interface LineProps {
  labels: string[]; // x labels, one per point
  series: Series[];
  target?: { value: number; label: string };
  height?: number;
  ariaLabel: string;
  format?: (n: number) => string;
  fit?: boolean; // y axis spans the data instead of starting at 0
  area?: boolean; // soft fill under the first series
  marks?: { x: number; label: string }[]; // points on the first series; x in label positions (may be fractional)
}

/** The element's pixel width, so the SVG viewBox matches it and text never scales. */
function useWidth(fallback = 680): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

const PAD = { top: 12, right: 12, bottom: 24, left: 52 };

function niceTicks(max: number, count = 3): number[] {
  if (max <= 0) return [0];
  const step0 = max / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0) ?? step0;
  const ticks = [0];
  while (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step); // top tick covers the max
  return ticks;
}

export function LineChart({ labels, series, target, height = 220, ariaLabel, format = compact, fit = false, area = false, marks = [] }: LineProps) {
  const fillId = `fill${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const hidden = useContext(PrivacyContext);
  const [hover, setHover] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const [box, W] = useWidth();
  const n = labels.length;
  if (n < 2) return null;
  const all = series.flatMap(s => s.values).concat(target ? [target.value] : []);
  let yMin = 0;
  let ticks = niceTicks(Math.max(...all) * 1.05);
  if (fit) {
    const lo = Math.min(...all);
    const hi = Math.max(...all);
    const pad = (hi - lo) * 0.15 || hi * 0.02 || 1;
    yMin = lo - pad;
    ticks = [yMin + (hi + pad - yMin) / 2, hi + pad];
  }
  const yMax = ticks[ticks.length - 1] || 1;
  const iw = W - PAD.left - PAD.right;
  const ih = height - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (i / (n - 1)) * iw;
  const y = (v: number) => PAD.top + ih - ((Math.max(v, yMin) - yMin) / (yMax - yMin)) * ih;

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const r = svg.current!.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    setHover(Math.min(n - 1, Math.max(0, Math.round(((px - PAD.left) / iw) * (n - 1)))));
  }

  const hx = hover != null ? x(hover) : 0;
  return (
    <figure className="chart">
      {series.length > 1 && (
        <figcaption className="chart-legend">
          {series.map(s => (
            <span key={s.name}>
              <svg width="22" height="8" aria-hidden>
                <line x1="0" y1="4" x2="22" y2="4" className={`ln ${s.style}`} />
              </svg>
              {s.name}
            </span>
          ))}
        </figcaption>
      )}
      <div className="chart-box" ref={box}>
        <svg
          ref={svg}
          viewBox={`0 0 ${W} ${height}`}
          role="img"
          aria-label={ariaLabel}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          {ticks.map(t => (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="grid" />
              {!hidden && (
                <text x={PAD.left - 8} y={y(t)} className="tick" textAnchor="end" dominantBaseline="middle">
                  {format(t)}
                </text>
              )}
            </g>
          ))}
          <text x={PAD.left} y={height - 6} className="tick">
            {labels[0]}
          </text>
          <text x={W - PAD.right} y={height - 6} className="tick" textAnchor="end">
            {labels[n - 1]}
          </text>
          {target && (
            <g>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(target.value)} y2={y(target.value)} className="target" />
              <text x={W - PAD.right} y={y(target.value) - 6} className="tick strong" textAnchor="end">
                {target.label}
              </text>
            </g>
          )}
          {area && (
            <>
              <defs>
                <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" className="area-top" />
                  <stop offset="1" className="area-bottom" />
                </linearGradient>
              </defs>
              <polygon
                points={`${x(0)},${PAD.top + ih} ${series[0].values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')} ${x(n - 1)},${PAD.top + ih}`}
                fill={`url(#${fillId})`}
              />
            </>
          )}
          {series.map(s => (
            <polyline
              key={s.name}
              points={s.values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')}
              className={`ln ${s.style}`}
            />
          ))}
          {marks
            .filter(mk => mk.x >= 0 && mk.x <= n - 1)
            .map(mk => {
              const vs = series[0].values;
              const i0 = Math.floor(mk.x);
              const i1 = Math.min(n - 1, i0 + 1);
              const v = vs[i0] + (vs[i1] - vs[i0]) * (mk.x - i0);
              return (
                <g key={mk.label + mk.x}>
                  <circle cx={x(mk.x)} cy={y(v)} r="4.5" className="mark" />
                  <text x={x(mk.x)} y={y(v) - 10} className="tick strong" textAnchor="middle">
                    {mk.label}
                  </text>
                </g>
              );
            })}
          {hover != null && (
            <g>
              <line x1={hx} x2={hx} y1={PAD.top} y2={PAD.top + ih} className="cross" />
              {series.map(s => (
                <circle key={s.name} cx={hx} cy={y(s.values[hover])} r="4" className={`dot ${s.style}`} />
              ))}
            </g>
          )}
        </svg>
        {hover != null && (
          <div className="tip" style={{ left: `${(hx / W) * 100}%` }}>
            <strong>{labels[hover]}</strong>
            {series.map(s => (
              <span key={s.name}>
                {s.name} <b className="num">{hidden ? '••••' : format(s.values[hover])}</b>
              </span>
            ))}
          </div>
        )}
      </div>
    </figure>
  );
}

interface BarsProps {
  data: { label: string; a: number; b: number; a_s: string; b_s: string }[];
  names: [string, string]; // a: quiet, b: main
  ariaLabel: string;
  height?: number;
  onPick?(index: number): void; // click a period
  selected?: number;
}

/** Two series per period, side by side; one y scale. */
export function PairBars({ data, names, ariaLabel, height = 180, onPick, selected }: BarsProps) {
  const hidden = useContext(PrivacyContext);
  const [hover, setHover] = useState<number | null>(null);
  const [box, W] = useWidth();
  const max = Math.max(1, ...data.flatMap(d => [d.a, d.b]));
  const ticks = niceTicks(max);
  const yMax = ticks[ticks.length - 1] || 1;
  const iw = W - PAD.left - PAD.right;
  const ih = height - PAD.top - PAD.bottom;
  const slot = iw / data.length;
  const bw = Math.min(22, slot / 3);
  const y = (v: number) => PAD.top + ih - (v / yMax) * ih;
  return (
    <figure className="chart">
      <figcaption className="chart-legend">
        <span>
          <i className="sw quiet" />
          {names[0]}
        </span>
        <span>
          <i className="sw main" />
          {names[1]}
        </span>
      </figcaption>
      <div className="chart-box" ref={box}>
        <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label={ariaLabel} onPointerLeave={() => setHover(null)}>
          {ticks.map(t => (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="grid" />
              {!hidden && (
                <text x={PAD.left - 8} y={y(t)} className="tick" textAnchor="end" dominantBaseline="middle">
                  {compact(t)}
                </text>
              )}
            </g>
          ))}
          {data.map((d, i) => {
            const cx = PAD.left + slot * i + slot / 2;
            return (
              <g
                key={d.label}
                onPointerEnter={() => setHover(i)}
                onClick={onPick ? () => onPick(i) : undefined}
                style={onPick ? { cursor: 'pointer' } : undefined}
              >
                <rect x={PAD.left + slot * i} y={PAD.top} width={slot} height={ih} className="hit" />
                <rect x={cx - bw - 1} y={y(d.a)} width={bw} height={Math.max(0, PAD.top + ih - y(d.a))} rx="2" className="bar quiet" />
                <rect x={cx + 1} y={y(d.b)} width={bw} height={Math.max(0, PAD.top + ih - y(d.b))} rx="2" className="bar main" />
                <text x={cx} y={height - 6} className={`tick ${hover === i || selected === i ? 'strong' : ''}`} textAnchor="middle">
                  {d.label}
                </text>
              </g>
            );
          })}
        </svg>
        {hover != null && (
          <div className="tip" style={{ left: `${((PAD.left + slot * hover + slot / 2) / W) * 100}%` }}>
            <strong>{data[hover].label}</strong>
            <span>
              {names[0]} <b className="num">{hidden ? '••••' : data[hover].a_s}</b>
            </span>
            <span>
              {names[1]} <b className="num">{hidden ? '••••' : data[hover].b_s}</b>
            </span>
          </div>
        )}
      </div>
    </figure>
  );
}
