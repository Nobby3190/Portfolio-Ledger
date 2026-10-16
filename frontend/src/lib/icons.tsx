import type { ReactNode } from 'react';
import { BRANDS, type BrandSlug, brandOf } from './brands';

/** Hand-drawn line icons for account types and income/expense categories (DESIGN.md 2「圖示」).
 *  24×24, stroked in currentColor so they follow the theme tokens. */
const PATHS = {
  candles: (
    <>
      <path d="M7 3v4M7 15v4M17 6v5M17 18v3" />
      <rect x="5" y="7" width="4" height="8" rx="1" />
      <rect x="15" y="11" width="4" height="7" rx="1" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z" />
    </>
  ),
  bank: <path d="M3 9.5 12 4l9 5.5M5.5 10.5v7M10 10.5v7M14 10.5v7M18.5 10.5v7M3 20h18" />,
  cash: (
    <>
      <rect x="2.5" y="6" width="19" height="12" rx="2" />
      <circle cx="12" cy="12" r="2.6" />
      <path d="M6 9.5v5M18 9.5v5" />
    </>
  ),
  card: (
    <>
      <rect x="2.5" y="5" width="19" height="14" rx="2" />
      <path d="M2.5 10h19M6 15h4" />
    </>
  ),
  hourglass: <path d="M6 3h12M6 21h12M7.5 3v2.5L12 12l4.5-6.5V3M7.5 21v-2.5L12 12l4.5 6.5V21" />,
  loan: (
    <>
      <path d="M3.5 11 12 4l8.5 7M6 9.5V20h12V9.5M14.5 12l-5 5" />
      <circle cx="10" cy="12.5" r="0.9" />
      <circle cx="14" cy="16.5" r="0.9" />
    </>
  ),
  house: <path d="M3.5 11 12 4l8.5 7M6 9.5V20h12V9.5M10 20v-5h4v5" />,
  bowl: <path d="M3.5 12h17a8.5 7 0 0 1-17 0zM9 20.5h6M13 9.5l2.5-6.5M15 9.5l5-5" />,
  bus: (
    <>
      <rect x="5" y="3" width="14" height="15" rx="2.5" />
      <path d="M5 11h14M8 18v2.5M16 18v2.5" />
      <circle cx="8.5" cy="14.5" r="0.8" />
      <circle cx="15.5" cy="14.5" r="0.8" />
    </>
  ),
  bag: <path d="M5 8h14l-1 12.5H6L5 8zM9 8V6.5a3 3 0 0 1 6 0V8" />,
  ticket: <path d="M3 7h18v3a2 2 0 0 0 0 4v3H3v-3a2 2 0 0 0 0-4V7zM14 7v2M14 11v2M14 15v2" />,
  medical: <path d="M9.5 3.5h5v6h6v5h-6v6h-5v-6h-6v-5h6z" />,
  book: <path d="M12 6.5C10.5 5 8 4.5 3.5 4.5v14c4.5 0 7 .5 8.5 2 1.5-1.5 4-2 8.5-2v-14c-4.5 0-7 .5-8.5 2zM12 6.5v14" />,
  shield: <path d="M12 3 5 6v5.5c0 4.5 3 7.8 7 9.5 4-1.7 7-5 7-9.5V6l-7-3zM9 12l2 2 4-4" />,
  percent: (
    <>
      <path d="M18 6 6 18" />
      <circle cx="7.5" cy="7.5" r="2.5" />
      <circle cx="16.5" cy="16.5" r="2.5" />
    </>
  ),
  briefcase: (
    <>
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M3 12.5h18" />
    </>
  ),
  gift: (
    <>
      <rect x="4" y="10" width="16" height="10.5" rx="1" />
      <path d="M3 7h18v3H3zM12 7v13.5M12 7c-1.5-3.5-5.5-3.5-5.5-1.5S9.5 7 12 7zm0 0c1.5-3.5 5.5-3.5 5.5-1.5S14.5 7 12 7z" />
    </>
  ),
  coin: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M14.5 9.2c-.5-.8-1.4-1.2-2.5-1.2-1.4 0-2.5.8-2.5 2s1.1 1.6 2.5 2 2.5.8 2.5 2-1.1 2-2.5 2c-1.1 0-2-.4-2.5-1.2M12 6.5V8M12 16v1.5" />
    </>
  ),
  transfer: <path d="M4 8h15M15 4l4 4-4 4M20 16H5M9 12l-4 4 4 4" />,
  check: <path d="M5 12.5 10 17.5 19 7" />,
  report: (
    <>
      <rect x="5" y="4.5" width="14" height="16.5" rx="2" />
      <path d="M9 3h6v3H9zM8.5 11h7M8.5 14.5h7M8.5 18h4" />
    </>
  ),
  dots: (
    <g fill="currentColor" stroke="none">
      <circle cx="6" cy="12" r="1.5" />
      <circle cx="12" cy="12" r="1.5" />
      <circle cx="18" cy="12" r="1.5" />
    </g>
  ),
  tag: (
    <>
      <path d="M3.5 12.5v-8a1 1 0 0 1 1-1h8l8 8-9 9-8-8z" />
      <circle cx="8" cy="8" r="1.4" />
    </>
  ),
  chart: <path d="M4 19.5h16M6 15l4-4 3 3 5-6.5" />,
  wallet: (
    <>
      <rect x="3" y="7" width="18" height="12.5" rx="2.5" />
      <path d="M16 13.2h2M5 7l9-3.2 2 3.2" />
    </>
  ),
  flag: <path d="M6 21V4M6 4h11.5l-2.2 4 2.2 4H6" />,
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
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {PATHS[name as keyof typeof PATHS]}
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

/** Solid colour square at the start of a row; brand logos and expenses without a known category use
 *  the brand slate, income the silver-blue, everything else grey. */
export function IconBadge({ name, tone = 'neutral' }: { name: IconName; tone?: IconTone }) {
  const hue = tone === 'income' ? 'income' : (ICON_TONES[name as keyof typeof PATHS] ?? (tone === 'expense' ? 'expense' : 'neutral'));
  return (
    <span className={`icon-badge ${tone} solid`} style={{ '--t': `var(--tone-${hue})` } as React.CSSProperties}>
      <Icon name={name} />
    </span>
  );
}

/** The same colour for a category name, for tiles and chips that show no icon. */
export const categoryTone = (name: string | null, kind: string) =>
  kind === 'income' ? 'var(--tone-income)' : `var(--tone-${ICON_TONES[categoryIcon(name, kind) as keyof typeof PATHS] ?? 'expense'})`;

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
  [['購', '買', '衣'], 'bag'],
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
