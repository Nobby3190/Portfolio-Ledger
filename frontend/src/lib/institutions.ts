/** Banks and brokers, to tell accounts apart by colour and to fill in a new account's name (DESIGN.md 2「帳戶」).
 *  Colours are near each brand's own, toned to read on both the light and the dark card (≥ 3:1).
 *  They only mark accounts (a bar, a badge); red/green on numbers still mean gains/losses. */

export type InstitutionKind = 'bank' | 'broker';

export interface Institution {
  name: string; // short name used for new accounts: 台新 → 台新信用卡
  words: string[]; // found anywhere in an account name, case-insensitive
  color: string;
  kinds: InstitutionKind[];
}

export const INSTITUTIONS: Institution[] = [
  { name: '國泰', words: ['國泰', 'cathay', 'cube'], color: '#3d9a4a', kinds: ['bank', 'broker'] },
  { name: '台新', words: ['台新', 'richart', 'taishin'], color: '#d64545', kinds: ['bank', 'broker'] },
  { name: '富邦', words: ['富邦', 'fubon'], color: '#2f6fbf', kinds: ['bank', 'broker'] },
  { name: '玉山', words: ['玉山', 'esun'], color: '#0f8a8a', kinds: ['bank', 'broker'] },
  { name: '中信', words: ['中信', '中國信託', 'ctbc'], color: '#c4476b', kinds: ['bank', 'broker'] },
  { name: '永豐', words: ['永豐', 'sinopac', '大戶'], color: '#d4731c', kinds: ['bank', 'broker'] },
  { name: '聯邦', words: ['聯邦', '吉鶴'], color: '#8a5cc2', kinds: ['bank'] },
  { name: '元大', words: ['元大', 'yuanta'], color: '#b38a12', kinds: ['bank', 'broker'] },
  { name: '凱基', words: ['凱基', 'kgi'], color: '#5560c8', kinds: ['bank', 'broker'] },
  { name: '第一', words: ['第一銀', '第一金', '一銀'], color: '#2b8fc6', kinds: ['bank', 'broker'] },
  { name: '兆豐', words: ['兆豐', 'mega'], color: '#b5533a', kinds: ['bank', 'broker'] },
  { name: '台銀', words: ['台銀', '臺銀', '台灣銀行', '臺灣銀行'], color: '#6b8e23', kinds: ['bank'] },
  { name: '郵局', words: ['郵局', '中華郵政'], color: '#2e8b57', kinds: ['bank'] },
  { name: '華南', words: ['華南'], color: '#d0623a', kinds: ['bank', 'broker'] },
  { name: '合庫', words: ['合庫', '合作金庫'], color: '#3973ac', kinds: ['bank'] },
  { name: '新光', words: ['新光'], color: '#c9553f', kinds: ['bank'] },
  { name: 'LINE Bank', words: ['line bank', 'linebank'], color: '#20a456', kinds: ['bank'] },
  { name: '將來', words: ['將來'], color: '#9b59b6', kinds: ['bank'] },
  { name: '樂天', words: ['樂天', 'rakuten'], color: '#c0306a', kinds: ['bank'] },
  { name: '群益', words: ['群益'], color: '#4a7fbf', kinds: ['broker'] },
  { name: '統一', words: ['統一證'], color: '#c47a18', kinds: ['broker'] },
];

/** Colours to pick by hand; also where an account no institution matches gets its colour from. */
export const SWATCHES = ['#5b7690', '#2f6fbf', '#0f8a8a', '#3d9a4a', '#b38a12', '#d4731c', '#d64545', '#c4476b', '#8a5cc2', '#7f8b99'];

/** The bank or broker an account name names: 國泰CUBE → 國泰; 外幣存款 → null. */
export function institutionOf(name: string): Institution | null {
  const s = name.normalize('NFKC').toLowerCase();
  return INSTITUTIONS.find(i => i.words.some(w => s.includes(w))) ?? null;
}

/** An account's colour: picked by hand, else its institution's, else (cash: slate) one of SWATCHES chosen by its name. */
export function accountColor(a: { name: string; type?: string; color?: string | null }): string {
  if (a.color) return a.color;
  const inst = institutionOf(a.name);
  if (inst) return inst.color;
  if (a.type === 'cash') return SWATCHES[0];
  let h = 0;
  for (const ch of a.name) h = (h * 31 + ch.codePointAt(0)!) >>> 0;
  return SWATCHES[h % SWATCHES.length];
}
