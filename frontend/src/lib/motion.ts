import { createContext, useEffect, useState } from 'react';

const QUERY = '(prefers-reduced-motion: reduce)';

/** True while the system asks for reduced motion; animations then show the end state at once. */
export function useReducedMotion(): boolean {
  const [reduce, setReduce] = useState(() => window.matchMedia(QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(QUERY);
    const on = () => setReduce(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return reduce;
}

/** Ids of the entries just saved, so their rows can flash once (DESIGN.md「動態與回饋」). */
export const FreshContext = createContext<ReadonlySet<number>>(new Set());
