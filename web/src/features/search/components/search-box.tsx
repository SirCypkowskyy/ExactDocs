import { Search, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useEffectEvent, useRef, useState } from "react";
import { MAX_QUERY, normalizeQuery } from "@/shared/lib/search-query";
import { parseTags } from "@/shared/lib/tags";
import { useSearchNav } from "../hooks/use-search-nav";
import type { SearchContext } from "../model/context";
import { SearchTags } from "./search-tags";

export const INPUT_ID = "search-input";
export const RESULTS_ID = "search-results";
const DEBOUNCE_MS = 300;

/** True while a version's own search box is on the page; it owns the `/` key then. */
export const hasVersionBox = () => document.getElementById(INPUT_ID) !== null;

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

/**
 * The query box of a version. The query lives in the URL (`?q=`); typing updates it after a
 * short pause, Enter at once. `/` focuses the box from anywhere, Escape clears it, and ArrowDown
 * moves into the results.
 */
export function SearchBox({ ctx }: { ctx: SearchContext }) {
  const update = useSearchNav(ctx.owner, ctx.repo);
  const input = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(ctx.q ?? "");
  // `committed` is what this box last wrote to the URL; a different `q` came from elsewhere
  // (back button, a link) and replaces the draft. Adjusting state while rendering, not an effect.
  const [committed, setCommitted] = useState(ctx.q);
  const [seen, setSeen] = useState(ctx.q);
  if (ctx.q !== seen) {
    setSeen(ctx.q);
    if (ctx.q !== committed) {
      setCommitted(ctx.q);
      setDraft(ctx.q ?? "");
    }
  }

  // Clearing the query clears `match` with it: a hidden "all" must not come back on the next search.
  const commit = (value: string, mode: "replace" | "push" = "push") => {
    const q = normalizeQuery(value);
    if (q === committed) return;
    setCommitted(q);
    void update(q ? { q } : { q, match: undefined }, mode);
  };

  // Typing replaces the history entry; Enter, Escape and the clear button push one.
  const settle = useEffectEvent((value: string) => commit(value, "replace"));
  useEffect(() => {
    const timer = setTimeout(() => settle(draft), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [draft]);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTyping(event.target)) return;
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
        commit("");
      }
    }
  }

  return (
    <div className="space-y-3">
      <search aria-label={ctx.ref}>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            commit(draft);
          }}
        >
          <label htmlFor={INPUT_ID} className="sr-only">
            Search {ctx.ref}
          </label>
          <div className="relative">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <input
              ref={input}
              id={INPUT_ID}
              type="search"
              autoComplete="off"
              spellCheck={false}
              enterKeyHint="search"
              aria-keyshortcuts="/"
              maxLength={MAX_QUERY}
              placeholder={`Search ${ctx.ref}`}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onKeyDown}
              aria-controls={ctx.q ? RESULTS_ID : undefined}
              className="h-11 w-full min-w-0 rounded-md bg-card pr-16 pl-9 text-base outline-none ring-1 ring-inset ring-input transition-shadow duration-150 [appearance:none] placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring sm:text-sm [&::-webkit-search-cancel-button]:hidden"
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
                  commit("");
                  input.current?.focus();
                }}
                className="absolute top-0 right-0 inline-flex size-11 cursor-pointer items-center justify-center rounded-md text-muted-foreground outline-none transition-transform duration-150 focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.95] [@media(hover:hover)]:hover:text-foreground"
              >
                <X aria-hidden="true" className="size-4" />
              </button>
            )}
          </div>
        </form>
      </search>
      {ctx.q && (
        <SearchTags
          ctx={ctx}
          tagCount={parseTags(ctx.tags).length}
          onTags={(tags) =>
            void update(parseTags(tags).length > 1 ? { tags } : { tags, match: undefined })
          }
          onMatch={(match) => void update({ match: match === "all" ? "all" : undefined })}
        />
      )}
    </div>
  );
}
