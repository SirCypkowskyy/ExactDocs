import { useState } from "react";

/**
 * Dismissals last for the browser session (blocks-map §1: "Dismiss, for the session"): kept in
 * `sessionStorage`, so a reload keeps a notice away and a new session shows it again. Each key
 * names the notice and the state that raised it, so a new state shows again at once. Storage may
 * be missing or refuse (private modes, a full quota): the notice then stays away until a reload.
 */
const STORAGE_KEY = "exactdocs-dismissed-notices";

function read(): readonly string[] {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((k): k is string => typeof k === "string") : [];
  } catch {
    return [];
  }
}

function write(keys: readonly string[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(keys));
  } catch {
    // Kept in memory for this page only.
  }
}

/** The dismissed keys and a way to add one. */
export function useDismissed() {
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(() => new Set(read()));
  function dismiss(key: string) {
    if (dismissed.has(key)) return;
    const next = new Set(dismissed).add(key);
    write([...next]);
    setDismissed(next);
  }
  return { dismissed, dismiss };
}
