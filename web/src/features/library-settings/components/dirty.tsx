import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";

/*
 * Which settings sections hold edits that are not saved yet. Each form reports its own state, and
 * the section nav shows a dot beside the ones that do (DESIGN.md, States).
 */
type Report = (id: string, dirty: boolean) => void;

const Reporter = createContext<Report>(() => {});
const Dirty = createContext<ReadonlySet<string>>(new Set());

export function DirtyProvider({ children }: { children: ReactNode }) {
  const [dirty, setDirty] = useState<ReadonlySet<string>>(new Set());
  const report = useCallback<Report>((id, isDirty) => {
    setDirty((prev) => {
      if (prev.has(id) === isDirty) return prev;
      const next = new Set(prev);
      if (isDirty) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);
  return (
    <Reporter.Provider value={report}>
      <Dirty.Provider value={dirty}>{children}</Dirty.Provider>
    </Reporter.Provider>
  );
}

/** A form says whether it holds unsaved edits; the report is withdrawn when it unmounts. */
export function useReportDirty(id: string, dirty: boolean) {
  const report = useContext(Reporter);
  useEffect(() => {
    report(id, dirty);
    return () => report(id, false);
  }, [id, dirty, report]);
}

export const useDirtySections = () => useContext(Dirty);
