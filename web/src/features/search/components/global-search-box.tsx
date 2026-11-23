import { useLocation, useNavigate } from "@tanstack/react-router";
import { Search, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useEffectEvent, useRef, useState } from "react";
import { common, useMessages } from "@/shared/lib/i18n";
import { MAX_QUERY, normalizeQuery } from "@/shared/lib/search-query";
import { cn } from "@/shared/lib/utils";
import { control, controlHeight, kbd } from "@/shared/ui/recipes";
import { Tooltip } from "@/shared/ui/tooltip";
import { messages } from "../messages";
import { hasVersionBox } from "./keyboard";

const GLOBAL_INPUT_ID = "global-search-input";
export const GLOBAL_RESULTS_ID = "global-search-results";
const DEBOUNCE_MS = 300;

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

interface Props {
  /** Where the box sits: the header, or the top of the phone's `/search` page. */
  place?: "header" | "page";
  /** Focus the box on mount. */
  autoFocus?: boolean;
  /** A taller field with a larger hint: the search page's own box. */
  prominent?: boolean;
  className?: string;
}

/**
 * Searches the default version of every library. Enter opens `/search`; once there, typing updates
 * `?q=` after a pause. `/` focuses it unless the page has its own per-version box, Escape clears
 * it, ArrowDown moves into the results.
 */
export function GlobalSearchBox({
  place = "header",
  autoFocus = false,
  prominent = false,
  className,
}: Props) {
  const t = useMessages(messages);
  const c = useMessages(common);
  const navigate = useNavigate();
  const onSearch = useLocation({ select: (l) => l.pathname === "/search" });
  const urlQ = useLocation({
    select: (l) =>
      l.pathname === "/search" ? normalizeQuery(String(l.search.q ?? "")) : undefined,
  });
  const input = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(urlQ ?? "");
  // `sent` is what this box last wrote to the URL. A different `q` came from elsewhere (Back, a
  // link, the other box) and replaces the draft; the URL lagging behind the input must not.
  const [sent, setSent] = useState(urlQ);
  const [seen, setSeen] = useState(urlQ);
  if (urlQ !== seen) {
    setSeen(urlQ);
    if (urlQ !== sent) {
      setSent(urlQ);
      setDraft(urlQ ?? "");
    }
  }

  const go = (value: string, replace: boolean) => {
    const q = normalizeQuery(value);
    if (q === sent || (!q && !onSearch)) return;
    setSent(q);
    void navigate({ to: "/search", search: q ? { q } : {}, replace });
  };
  const settle = useEffectEvent((value: string) => {
    if (onSearch) go(value, true);
  });
  useEffect(() => {
    const timer = setTimeout(() => settle(draft), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [draft]);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTyping(event.target) || hasVersionBox()) return;
      event.preventDefault();
      input.current?.focus();
      input.current?.select();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      const first = document.querySelector<HTMLElement>(`#${GLOBAL_RESULTS_ID} a[data-result]`);
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
    <search
      aria-label={t.box.allLibraries}
      className={cn(
        "min-w-0 flex-1",
        // The page's own box replaces the band's on /search: one field, not two.
        place === "header" && "[body:has(#global-search-input-page)_&]:hidden",
        className,
      )}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          go(draft, false);
        }}
      >
        <label htmlFor={`${GLOBAL_INPUT_ID}-${place}`} className="sr-only">
          {t.box.searchAll}
        </label>
        <div className="relative">
          <Search
            aria-hidden="true"
            className={cn(
              "pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground",
              prominent ? "size-5" : "size-4",
            )}
          />
          <input
            ref={input}
            id={`${GLOBAL_INPUT_ID}-${place}`}
            data-global-search=""
            // biome-ignore lint/a11y/noAutofocus: the phone's search page exists to type into this box
            autoFocus={autoFocus}
            type="search"
            autoComplete="off"
            spellCheck={false}
            enterKeyHint="search"
            aria-keyshortcuts="/"
            maxLength={MAX_QUERY}
            placeholder={t.box.searchAll}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            className={cn(
              control,
              controlHeight,
              "min-w-0 pr-16 pl-9 [appearance:none] [&::-webkit-search-cancel-button]:hidden",
              prominent && "h-12 pl-11 text-section fine:h-12",
            )}
          />
          {draft === "" ? (
            // Hidden while the page has its own box: that one answers `/`, not this.
            <kbd
              className={cn(
                kbd,
                "pointer-events-none absolute top-1/2 right-3 hidden -translate-y-1/2 sm:inline-flex [body:has(#search-input)_&]:hidden",
              )}
            >
              /
            </kbd>
          ) : (
            <Tooltip label={c.clearSearch}>
              <button
                type="button"
                aria-label={c.clearSearch}
                onClick={() => {
                  setDraft("");
                  go("", false);
                  input.current?.focus();
                }}
                className={cn(
                  "absolute top-0 right-0 inline-flex size-11 cursor-pointer items-center justify-center rounded-md text-muted-foreground outline-none transition-transform duration-(--dur-fast) focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] sm:size-9 can-hover:hover:text-foreground",
                  prominent && "sm:top-1.5 sm:right-1",
                )}
              >
                <X aria-hidden="true" className="size-4" />
              </button>
            </Tooltip>
          )}
        </div>
      </form>
    </search>
  );
}
