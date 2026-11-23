import { useEffect, useSyncExternalStore } from "react";
import { type ApiPath, getJson, HttpError, sendJson } from "@/shared/lib/http";
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
 */

// Not in the generated schema until the backend ships it (#487); see web/openapi.json.
const PATH = "/v1/account/preferences" as ApiPath;
const SAVE_DELAY_MS = 500;

type AccountPreferences = { saved: boolean; preferences: Preferences };
type Status = "browser" | "saving" | "saved" | "unavailable" | "error";

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
        else await sendJson<AccountPreferences>("PUT", PATH, readPreferences());
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

/** One sentence on where the choices are kept, for the Interface tab. */
export function usePreferencesStatus(): string {
  const t = useMessages(messages);
  const current = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => status,
    () => status,
  );
  return t.preferences[current];
}
