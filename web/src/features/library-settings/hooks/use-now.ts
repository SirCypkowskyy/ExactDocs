import { useEffect, useState } from "react";

/** The clock, refreshed every minute so "checked 3 minutes ago" stays true on a page left open. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);
  return now;
}
