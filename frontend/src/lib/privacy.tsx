import { createContext, useContext } from 'react';

export const PrivacyContext = createContext(false);

/** A money string, masked while privacy mode is on. Percentages are left alone by callers. */
export function Money({ value, className }: { value: string | null | undefined; className?: string }) {
  const hidden = useContext(PrivacyContext);
  if (value == null) return null;
  return <span className={className}>{hidden ? value.replace(/[\d,.]+/, '••••') : value}</span>;
}

export function signClass(sign: number): string {
  return sign > 0 ? 'up' : sign < 0 ? 'down' : '';
}
