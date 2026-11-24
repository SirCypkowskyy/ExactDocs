import { useCallback, useEffect, useRef, useState } from "react";

/**
 * A short "done" moment for a button (Copied, Saved): `flash()` turns it on, it turns itself off
 * after `ms`. A second flash restarts the wait.
 */
export function useFlash(ms = 1500): [on: boolean, flash: () => void] {
  const [on, setOn] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const flash = useCallback(() => {
    clearTimeout(timer.current);
    setOn(true);
    timer.current = setTimeout(() => setOn(false), ms);
  }, [ms]);
  return [on, flash];
}
