import { useLocation, useNavigate } from "@tanstack/react-router";
import { Search, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useEffectEvent, useRef, useState } from "react";
import { MAX_QUERY, normalizeQuery } from "@/shared/lib/search-query";
import { RESULTS_ID } from "./search-box";

export const GLOBAL_INPUT_ID = "global-search-input";
const DEBOUNCE_MS = 300;

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

/**
 * The header's search box: searches the default version of every library. Enter opens `/search`;
 * once there, typing updates `?q=` after a pause. `/` focuses it unless the page has its own
 * (per-version) box, Escape clears it, ArrowDown moves into the results.
 */
export function GlobalSearchBox() {
  const navigate = useNavigate();
  const onSearch = useLocation({ select: (l) => l.pathname === "/search" });
  const urlQ = useLocation({
    select: (l) =>
      l.pathname === "/search" ? normalizeQuery(String(l.search.q ?? "")) : undefined,
  });
  const input = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(urlQ ?? "");
  const [seen, setSeen] = useState(urlQ);
  // A different `q` in the URL (Back, a link, leaving /search) replaces the draft.
  if (urlQ !== seen) {
    setSeen(urlQ);
    if (urlQ !== normalizeQuery(draft)) setDraft(urlQ ?? "");
  }

  const go = (value: string, replace: boolean) => {
    const q = normalizeQuery(value);
    if (q === urlQ || (!q && !onSearch)) return;
    void navigate({ to: "/search", search: q ? { q } : {}, replace });
  };
  const settle = useEffectEvent((value: string) => onSearch && go(value, true));
  useEffect(() => {
    const timer = setTimeout(() => settle(draft), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [draft]);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTyping(event.target) || document.getElementById("search-input")) return;
      event.preventDefault();
      input.current?.focus();
      input.current?.select();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      const first = document.querySelector<HTMLElement>(`#${RESULTS_ID} a[data-result]`);
      if (first) {
        event.preventDefault();
        first.focus();
      }
    } else if (event.key === "Escape") {
      if (draft === "") input.current?.blur();
      else {
        setDraft("");
        go("", false);
      }
    }
  }

  return (
    <search className="min-w-0 flex-1 sm:max-w-sm">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          go(draft, false);
        }}
      >
        <label htmlFor={GLOBAL_INPUT_ID} className="sr-only">
          Search all libraries
        </label>
        <div className="relative">
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <input
            ref={input}
            id={GLOBAL_INPUT_ID}
            type="search"
            autoComplete="off"
            spellCheck={false}
            enterKeyHint="search"
            aria-keyshortcuts="/"
            maxLength={MAX_QUERY}
            placeholder="Search all libraries"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            className="h-11 w-full min-w-0 rounded-md bg-card pr-16 pl-9 text-base outline-none ring-1 ring-inset ring-input transition-shadow duration-150 [appearance:none] placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring sm:h-9 sm:text-sm [&::-webkit-search-cancel-button]:hidden"
          />
          {draft === "" ? (
            <kbd className="pointer-events-none absolute top-1/2 right-3 hidden h-5 min-w-5 -translate-y-1/2 items-center justify-center rounded bg-secondary px-1 font-mono text-xs text-muted-foreground lg:inline-flex">
              /
            </kbd>
          ) : (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => {
                setDraft("");
                go("", false);
                input.current?.focus();
              }}
              className="absolute top-0 right-0 inline-flex size-11 cursor-pointer items-center justify-center rounded-md text-muted-foreground outline-none transition-transform duration-150 focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.95] sm:size-9 [@media(hover:hover)]:hover:text-foreground"
            >
              <X aria-hidden="true" className="size-4" />
            </button>
          )}
        </div>
      </form>
    </search>
  );
}
