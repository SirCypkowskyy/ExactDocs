import { useEffect, useState } from "react";

/**
 * The clock, refreshed every `everyMs` (a minute by default) so "3 minutes ago" or "running 2 min"
 * stays true on a page left open.
 */
export function useNow(everyMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(id);
  }, [everyMs]);
  return now;
}
