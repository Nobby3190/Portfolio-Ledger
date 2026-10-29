import { type ReactNode, useId } from 'react';
import { BRANDS, type BrandSlug, brandOf } from './brands';

/** Hand-drawn icons for account types and income/expense categories (DESIGN.md 2「圖示」).
 *  24×24, stroked in currentColor so they follow the theme tokens. Geometric since 2026-10-23: flat
 *  ends, square or 45° corners, octagons for circles, and deliberate breaks between the parts. */
const F = { fill: 'currentColor', stroke: 'none' } as const; // the small solid parts

const PATHS = {
  candles: (
    <>
      <path d="M7 3v3M7 16v4M17 5v4M17 18.5v2.5" />
      <rect x="5.25" y="7.5" width="3.5" height="7" {...F} />
      <rect x="15.25" y="10.5" width="3.5" height="6.5" {...F} />
    </>
  ),
  globe: <path d="M8.3 3h7.4L21 8.3v7.4L15.7 21H8.3L3 15.7V8.3zM3 12h18M12 3 8.5 6.5v11L12 21M12 3l3.5 3.5v11L12 21" />,
  bank: <path d="M5 10l7-7 7 7M3 10h18M7 12.5v5M12 12.5v5M17 12.5v5M3 20h18" />,
  cash: (
    <path d="M4.5 6h15l2 2v8l-2 2h-15l-2-2V8zM10.9 9.4h2.2l1.5 1.5v2.2l-1.5 1.5h-2.2l-1.5-1.5v-2.2zM6 10v4M18 10v4" />
  ),
  card: <path d="M4.5 5h15l2 2v10l-2 2h-15l-2-2V7zM2.5 10h19M6 15h4" />,
  hourglass: <path d="M6 3h12M6 21h12M7.5 5.5h9L12 10zM7.5 18.5h9L12 14z" />,
  loan: (
    <>
      <path d="M4.5 11.5 12 4l7.5 7.5M6.5 13v7.5h11V13M14.5 12.5l-5 5" />
      <rect x="8.6" y="11.6" width="1.8" height="1.8" {...F} />
      <rect x="13.6" y="16.6" width="1.8" height="1.8" {...F} />
    </>
  ),
  house: <path d="M4.5 11.5 12 4l7.5 7.5M6.5 13v7.5h11V13M10 20.5v-5h4v5" />,
  bowl: <path d="M3.5 11.5h17L16 16H8zM9.5 19.5h5M10 9l5-5M17 9l3-3" />,
  bus: (
    <>
      <path d="M7 3h10l2 2v13H5V5zM5 10.5h14M7.5 18v3M16.5 18v3" />
      <rect x="7.1" y="13.1" width="1.8" height="1.8" {...F} />
      <rect x="15.1" y="13.1" width="1.8" height="1.8" {...F} />
    </>
  ),
  bag: <path d="M5 8h14v10.5l-2 2H7l-2-2zM9 8V4.5h6V8" />,
  ticket: <path d="M3 6.5h18V10l-2 2 2 2v3.5H3V14l2-2-2-2zM14.5 9v1.5M14.5 13.5V15" />,
  medical: <path d="M9.5 7V3.5h5V7M9.5 17v3.5h5V17M7 9.5H3.5v5H7M17 9.5h3.5v5H17" />,
  book: <path d="M12 7.5 9.5 5h-6v13h6l2.5 2.5M12 7.5 14.5 5h6v13h-6L12 20.5M12 10.5v7" />,
  shield: <path d="M5 4.5h14v8l-7 7-7-7zM9 11.5l2 2 4-4" />,
  percent: (
    <>
      <path d="M17.5 6.5l-11 11" />
      <rect x="4.5" y="4.5" width="3.5" height="3.5" {...F} />
      <rect x="16" y="16" width="3.5" height="3.5" {...F} />
    </>
  ),
  briefcase: <path d="M5 7h14l2 2v9.5l-2 2H5l-2-2V9zM9 7V4h6v3M3 13h6.5M14.5 13H21" />,
  gift: <path d="M3 7.5h18V11H3zM4.5 11v9.5h15V11M12 7.5v13M12 7.5 8.5 4v3.5zM12 7.5 15.5 4v3.5z" />,
  coin: (
    <path d="M8.5 3.5h7l5 5v7l-5 5h-7l-5-5v-7zM10 10h4v4h-4z" />
  ),
  transfer: <path d="M4 8h14M14.5 4.5 18 8l-3.5 3.5M20 16H6M9.5 12.5 6 16l3.5 3.5" />,
  check: <path d="M4.5 12l5 5L19.5 7" />,
  report: (
    <>
      <path d="M8 5H5v16h14V5h-3M8.5 11.5h7M8.5 15h7M8.5 18.5h4" />
      <rect x="9.5" y="3" width="5" height="3.5" {...F} />
    </>
  ),
  bell: <path d="M6 17v-7l3-3h6l3 3v7M4.5 17h15M10.5 20.5h3M12 3.5v2" />,
  dots: (
    <g {...F}>
      <path d="M6 10.25 7.75 12 6 13.75 4.25 12z" />
      <path d="M12 10.25 13.75 12 12 13.75 10.25 12z" />
      <path d="M18 10.25 19.75 12 18 13.75 16.25 12z" />
    </g>
  ),
  tag: (
    <>
      <path d="M3.5 12.5v-9h9l8 8-9 9z" />
      <rect x="6.5" y="6.5" width="2.5" height="2.5" {...F} />
    </>
  ),
  chart: <path d="M3.5 20h17M5 16.5 9.5 12l2.5 2.5M14 12.5l5-5" />,
  wallet: <path d="M5 7h14l2 2v9l-2 2H5l-2-2V9zM6 7l3-3h7v3M15 11.5h3.5V15H15z" />,
  flag: <path d="M6 21V3.5M8.5 4.5h10l-3 3 3 3h-10" />,
} satisfies Record<string, ReactNode>;

/** A line icon, or a brand logo (`brand:netflix`, from brands.ts). */
export type IconName = keyof typeof PATHS | `brand:${BrandSlug}`;
export type IconTone = 'expense' | 'income' | 'neutral';

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  if (name.startsWith('brand:')) {
    // Brand logos are filled and run edge to edge; the wider viewBox gives them the line icons' margin.
    return (
      <svg className="icon brand" width={size} height={size} viewBox="-2.5 -2.5 29 29" fill="currentColor" aria-hidden>
        <path d={BRANDS[name.slice(6) as BrandSlug].d} />
      </svg>
    );
  }
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      // Thin strokes vanish at chip size; a touch heavier there keeps the weight even.
      strokeWidth={size <= 14 ? 2.5 : 2.25}
      strokeLinecap="butt"
      strokeLinejoin="miter"
      strokeMiterlimit={4}
      aria-hidden
    >
      {PATHS[name as keyof typeof PATHS]}
    </svg>
  );
}

/** The app's mark (the Dock icon, packaging/make_icon.py, draws it on a tile): three ledger lines and a
 *  tick, no tile around it here (2026-10-23), in an indigo-to-violet gradient that follows the theme. */
export function BrandMark() {
  const id = useId();
  return (
    <svg className="brand-mark" viewBox="5 5 16 16" aria-hidden>
      <defs>
        {/* user space: on a horizontal line a bounding-box gradient has no height and draws nothing */}
        <linearGradient id={id} gradientUnits="userSpaceOnUse" x1="5" y1="5" x2="21" y2="21">
          <stop offset="0" style={{ stopColor: 'var(--logo-a)' }} />
          <stop offset="1" style={{ stopColor: 'var(--logo-b)' }} />
        </linearGradient>
      </defs>
      <g fill="none" stroke={`url(#${id})`} strokeWidth="2.6">
        <path d="M6 7h14M6 19h14" />
        <path d="M6 13h9M18 10v6" opacity="0.6" />
      </g>
    </svg>
  );
}

/** Each category icon's colour (DESIGN.md 2「大膽版」): neighbours of the slate blue, never red/green
 *  (those mean up/down) or amber (warnings). Income keeps the silver-blue; transfers and cash stay grey. */
const ICON_TONES: Partial<Record<keyof typeof PATHS, string>> = {
  bowl: 'sand',
  bus: 'sky',
  house: 'indigo',
  bag: 'plum',
  ticket: 'plum',
  medical: 'teal',
  book: 'sky',
  shield: 'teal',
  percent: 'sand',
  candles: 'indigo',
  globe: 'sky',
  hourglass: 'teal',
  coin: 'teal',
  card: 'indigo',
};

/** The tones a category can be given in 管理分類 (finance.CATEGORY_COLORS). The names are slots, not hues:
 *  each theme has its own set (indigo is orange in 亮色), so the swatches are only numbered. */
export const CATEGORY_COLORS = ['indigo', 'sky', 'teal', 'plum', 'sand', 'rose', 'ocean', 'stone'];

// The colours picked in 管理分類, by `${kind}:${name}`; App sets them from each state.
let customTones = new Map<string, string>();
export function setCategoryColors(cats: { name: string; kind: string; color: string | null }[]) {
  customTones = new Map(cats.filter(c => c.color).map(c => [`${c.kind}:${c.name}`, c.color!]));
}
const customTone = (name: string | null | undefined, kind: string) => (name ? customTones.get(`${kind}:${name}`) : undefined);

/** Solid colour square at the start of a row; brand logos and expenses without a known category use
 *  the brand slate, income the silver-blue, everything else grey. Given its category, a colour picked
 *  in 管理分類 wins (not over a brand logo). */
export function IconBadge({ name, tone = 'neutral', category }: { name: IconName; tone?: IconTone; category?: string | null }) {
  const custom = tone !== 'neutral' && !name.startsWith('brand:') ? customTone(category, tone) : undefined;
  const hue = custom ?? (tone === 'income' ? 'income' : (ICON_TONES[name as keyof typeof PATHS] ?? (tone === 'expense' ? 'expense' : 'neutral')));
  return (
    <span className={`icon-badge ${tone} solid`} style={{ '--t': `var(--tone-${hue})` } as React.CSSProperties}>
      <Icon name={name} />
    </span>
  );
}

/** The same colour for a category name, for tiles and chips that show no icon. */
export const categoryTone = (name: string | null, kind: string) =>
  `var(--tone-${customTone(name, kind) ?? autoTone(name, kind)})`;

/** A category's colour from its name (管理分類「自動」). */
export const autoTone = (name: string | null, kind: string) =>
  kind === 'income' ? 'income' : (ICON_TONES[categoryIcon(name, kind) as keyof typeof PATHS] ?? 'expense');

const ACCOUNT_ICONS: Record<string, IconName> = {
  broker_tw: 'candles',
  broker_us: 'globe',
  bank: 'bank',
  cash: 'cash',
  credit: 'card',
  deposit: 'hourglass',
  loan: 'loan',
};

export const accountIcon = (type: string): IconName => ACCOUNT_ICONS[type] ?? 'tag';

const CATEGORY_ICONS: Record<string, IconName> = {
  餐飲: 'bowl',
  交通: 'bus',
  居住: 'house',
  消費: 'bag',
  購物: 'bag',
  娛樂: 'ticket',
  醫療: 'medical',
  教育: 'book',
  保險: 'shield',
  貸款利息: 'percent',
  其他: 'dots',
  薪資: 'briefcase',
  獎金: 'gift',
  利息: 'coin',
  其他收入: 'dots',
};

// For categories the user made: the first entry whose word appears in the name wins.
const KEYWORDS: [string[], IconName][] = [
  [['餐', '吃', '飯', '食', '飲', '咖啡'], 'bowl'],
  [['車', '捷運', '油', '停車', '機票'], 'bus'],
  [['房', '租', '水電', '瓦斯', '管理費'], 'house'],
  [['消費', '購', '買', '衣'], 'bag'],
  [['娛樂', '電影', '遊戲', '旅'], 'ticket'],
  [['醫', '藥', '診'], 'medical'],
  [['教育', '書', '課', '學'], 'book'],
  [['保險'], 'shield'],
  [['貸'], 'percent'],
  [['薪'], 'briefcase'],
  [['獎', '紅包'], 'gift'],
];

export function categoryIcon(name: string | null, kind: string): IconName {
  if (!name) return 'tag';
  const exact = CATEGORY_ICONS[name];
  if (exact) return exact;
  if (name.includes('利息') || name.includes('股息')) return kind === 'income' ? 'coin' : 'percent';
  return KEYWORDS.find(([words]) => words.some(w => name.includes(w)))?.[1] ?? 'tag';
}

/** A ledger entry's icon: for income/expense the brand its note names (Netflix, Claude…) or else its
 *  category; otherwise what kind of move it was. */
export function txIcon(kind: string, category: string | null, text?: string | null): IconName {
  switch (kind) {
    case 'income':
    case 'expense': {
      const brand = brandOf(text);
      return brand ? `brand:${brand}` : categoryIcon(category, kind);
    }
    case 'transfer':
      return 'transfer';
    case 'repay':
      return 'loan';
    case 'cash_dividend':
      return 'coin';
    case 'deposit':
    case 'withdraw':
      return 'cash';
    default:
      return 'candles';
  }
}

export const toneOf = (kind: string): IconTone => (kind === 'expense' ? 'expense' : kind === 'income' ? 'income' : 'neutral');
