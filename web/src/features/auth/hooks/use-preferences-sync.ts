import { useEffect, useSyncExternalStore } from "react";
import { getJson, HttpError, sendJson } from "@/shared/lib/http";
import { useMessages } from "@/shared/lib/i18n";
import {
  adoptAccountPreferences,
  normalizePreferences,
  onPreferencesChange,
  type Preferences,
  readPreferences,
} from "@/shared/lib/preferences";
import { messages } from "../messages";

/*
 * Interface preferences follow the person (#487). Before sign-in they live in this browser; at
 * sign-in an account with nothing saved takes the browser's choices, an account with saved choices
 * wins; while signed in every change is saved (debounced, so a run of clicks is one request).
 *
 * `leaderboard_opt_in` (#510) is consent, not a look: it is always the account's own. A browser's
 * copy may be someone else's (the person before on a shared computer), so at sign-in the account's
 * answer replaces it even when the account saved nothing else, and only then is it sent back.
 */

const PATH = "/v1/account/preferences";
const SAVE_DELAY_MS = 500;

type AccountPreferences = { saved: boolean; preferences: Preferences };
export type PreferencesSyncStatus = "browser" | "saving" | "saved" | "unavailable" | "error";
type Status = PreferencesSyncStatus;

let status: Status = "browser";
const listeners = new Set<() => void>();
function setStatus(next: Status) {
  if (next === status) return;
  status = next;
  for (const listener of listeners) listener();
}

/** Mounted once in the signed-in shell. */
export function usePreferencesSync(signedIn: boolean) {
  useEffect(() => {
    if (!signedIn) {
      setStatus("browser");
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stop = () => {};
    const save = (prefs: Preferences) =>
      sendJson<AccountPreferences>("PUT", PATH, prefs)
        .then(() => !cancelled && setStatus("saved"))
        .catch(() => !cancelled && setStatus("error"));
    (async () => {
      try {
        const remote = await getJson<AccountPreferences>(PATH);
        if (cancelled) return;
        if (remote.saved) adoptAccountPreferences(normalizePreferences(remote.preferences));
        else {
          const consent = normalizePreferences(remote.preferences).leaderboard_opt_in;
          const local = readPreferences();
          if (local.leaderboard_opt_in !== consent) {
            adoptAccountPreferences({ ...local, leaderboard_opt_in: consent });
          }
          await sendJson<AccountPreferences>("PUT", PATH, readPreferences());
        }
        if (cancelled) return;
        setStatus("saved");
        stop = onPreferencesChange((prefs, source) => {
          if (source !== "local") return;
          clearTimeout(timer);
          setStatus("saving");
          timer = setTimeout(() => void save(prefs), SAVE_DELAY_MS);
        });
      } catch (error) {
        if (cancelled) return;
        // A server without #487 answers 404: the choices simply stay in this browser.
        setStatus(error instanceof HttpError && error.status === 404 ? "unavailable" : "error");
      }
    })();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      stop();
    };
  }, [signedIn]);
}

/**
 * Where the choices are kept now. `saved` and `saving` mean the account's copy was read, so an
 * account-only choice (the leaderboard opt-in) shows the account's answer.
 */
export function usePreferencesSyncStatus(): PreferencesSyncStatus {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => status,
    () => status,
  );
}

/** One sentence on where the choices are kept, for the Interface tab. */
export function usePreferencesStatus(): string {
  const t = useMessages(messages);
  return t.preferences[usePreferencesSyncStatus()];
}
