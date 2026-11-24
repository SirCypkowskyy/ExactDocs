import type { components } from "@/shared/lib/api-schema";

/*
 * The instance banner (blocks-map §1 "banner", chunk 11): what operators must act on, from
 * `GET /api/health` (alias of `/healthz`) and `GET /api/v1/ai/usage`. Three notices: the search
 * index needs a rebuild, the vector store's extension is missing, the instance's AI budget is
 * reached.
 */

/**
 * `GET /api/health` (`/healthz`): outside `/api/v1`, so not in the generated schema. When the
 * database did not answer in time its fields are `null`; an untrusted `Host` gets `status` only.
 */
export interface Health {
  status: string;
  version?: string | null;
  database_reachable?: boolean | null;
  reindex_required?: boolean | null;
  /** The extension the vector store cannot load (`sqlite-vec`, `vector`), else `null`. */
  vector_store_missing?: string | null;
}

export type AiUsage = components["schemas"]["AiUsageOut"];

export type Notice =
  | { kind: "reindex"; condition: string; dismissible: false }
  | { kind: "vector-store"; condition: string; dismissible: true; extension: string }
  | {
      kind: "budget";
      condition: string;
      dismissible: true;
      window: "day" | "month";
      resetsAt: string;
    };

/**
 * The notices to show, most serious first. `condition` names the state that raised each one, so a
 * dismissal covers that state only: another extension, or the budget of the next day or month,
 * shows again. A payload of another shape (an older server, a proxy's page) raises nothing: the
 * banner must never take the page down with it.
 */
export function noticesOf(health: Health | undefined, usage: AiUsage | undefined): Notice[] {
  const notices: Notice[] = [];
  if (health?.reindex_required === true) {
    notices.push({ kind: "reindex", condition: "required", dismissible: false });
  }
  const extension = health?.vector_store_missing;
  if (typeof extension === "string" && extension) {
    notices.push({ kind: "vector-store", condition: extension, dismissible: true, extension });
  }
  const scopes = Array.isArray(usage?.scopes) ? usage.scopes : [];
  const budgets = scopes.find((s) => s.scope === "instance")?.budgets;
  // The month's ceiling outlasts the day's: name the one that stays reached longest.
  const reached = (Array.isArray(budgets) ? budgets : [])
    .filter((b) => b.reached === true)
    .sort((a, b) => Date.parse(b.resets_at) - Date.parse(a.resets_at))[0];
  if (reached) {
    const window = reached.window === "month" ? "month" : "day";
    notices.push({
      kind: "budget",
      condition: `${window}:${reached.window_start}`,
      dismissible: true,
      window,
      resetsAt: reached.resets_at,
    });
  }
  return notices;
}

/** The key a dismissal is remembered under: the notice and the state that raised it. */
export const dismissKey = (notice: Notice): string => `${notice.kind}:${notice.condition}`;
