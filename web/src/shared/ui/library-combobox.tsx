import {
  keepPreviousData,
  type QueryKey,
  type UseQueryOptions,
  useQuery,
} from "@tanstack/react-query";
import { Check, ChevronsUpDown, CircleAlert, ListFilter, Plus } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useId, useMemo, useState } from "react";
import { common, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button } from "./button";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "./command";
import { LibraryMark } from "./library-mark";
import { messages } from "./messages";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";
import { trigger as triggerRecipe } from "./recipes";
import { Skeleton } from "./skeleton";
import { Tag, TagList } from "./tags";

/*
 * The library combobox (blocks-map §1 "combobox", after the free shadcnblocks Combobox Grouped 6
 * (`combobox-grouped-6`) and the grouping of Combobox Grouped 3; own code on Popover + Command):
 * one picker for every place that chooses a library (Playground, a token's scope, the jobs and
 * access-log filters, the global search). "Recent" (this browser) first, then every library, by
 * owner once there are more than 20. Typing filters; arrows, Home and End move, Enter picks,
 * Escape closes and focus goes back to the trigger. The input is a `combobox` that points at the
 * highlighted `option` with `aria-activedescendant` (cmdk); a live line says how many match.
 *
 * Data comes in from the feature (shared never fetches on its own): `options` (a list already at
 * hand), or `query` (a function from the typed text to the feature's queryOptions, asked for the
 * first time the list opens and again as the text changes).
 */

/** One library as the picker shows it. */
export interface LibraryOption {
  /** `/owner/repo`. */
  id: string;
  /** The display name, shown muted after the ID when it says more than the ID. */
  title?: string | undefined;
  /** The library's `logo` as the API sends it (its version), or null. */
  logo?: string | null | undefined;
  /** Something at the row's end, e.g. a match count (its meaning in `detailLabel`). */
  detail?: ReactNode;
  /** `detail` in words for a screen reader ("3 matches"). */
  detailLabel?: string | undefined;
}

/** What a `query` gives: the libraries that match, and how many match in all when it is more. */
export interface LibraryChoices {
  options: readonly LibraryOption[];
  /** Every match, when the list was cut short (a page of the API). */
  total?: number | undefined;
}

/** A feature's queryOptions for the libraries matching some text. */
export type LibraryChoicesQuery<K extends QueryKey = QueryKey> = UseQueryOptions<
  LibraryChoices,
  Error,
  LibraryChoices,
  K
>;

interface BaseProps<K extends QueryKey> {
  /** What is chosen ("Library", "Libraries"): the field's label, or the filter button's name. */
  label: string;
  /**
   * `field`: a labelled form control (the label above, the choice in the box, chips under it).
   * `filter`: an outline button for a table toolbar, like a faceted filter.
   */
  variant?: "field" | "filter";
  /** The trigger's text while nothing is chosen ("All libraries"). */
  placeholder?: string | undefined;
  /** Help under a field. */
  hint?: ReactNode;
  /** The libraries, when the feature already has them (with its query's `loading` and `failed`). */
  options?: readonly LibraryOption[] | undefined;
  /** `options` are still on their way. */
  loading?: boolean | undefined;
  /** `options` could not be loaded; `onRetry` asks again. */
  failed?: boolean | undefined;
  onRetry?: (() => void) | undefined;
  /** Or the feature's query for the libraries matching some text (debounced). */
  query?: ((text: string) => LibraryChoicesQuery<K>) | undefined;
  /** Offer the typed text itself when it passes (e.g. a removed library's `/owner/repo`). */
  custom?: ((text: string) => boolean) | undefined;
  /** A trigger of the caller's own (a "+3 more" button); it is given the popover's behaviour. */
  children?: ReactNode;
  /** The trigger's `id` (a field's label points at it). */
  id?: string | undefined;
  className?: string | undefined;
}

interface SingleProps<K extends QueryKey> extends BaseProps<K> {
  multiple?: false;
  value: string | undefined;
  onChange: (id: string | undefined) => void;
}

interface MultipleProps<K extends QueryKey> extends BaseProps<K> {
  multiple: true;
  value: readonly string[];
  onChange: (ids: string[]) => void;
}

export type LibraryComboboxProps<K extends QueryKey = QueryKey> = SingleProps<K> | MultipleProps<K>;

/** Above this many libraries the list is grouped by owner. */
const GROUP_FROM = 20;
/** Libraries kept in "Recent". */
const RECENT_MAX = 5;
const RECENT_KEY = "exactdocs-recent-libraries";
/** How long typing rests before a `query` asks again. */
const DEBOUNCE_MS = 200;

type Recent = { id: string; title?: string; logo?: string | null };

function readRecent(): Recent[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (r): r is Recent =>
          typeof r === "object" && r !== null && typeof (r as Recent).id === "string",
      )
      .slice(0, RECENT_MAX);
  } catch {
    return [];
  }
}

/** The libraries last picked in this browser, newest first (a convenience: never required). */
export function recentLibraries(): readonly Recent[] {
  return readRecent();
}

function rememberLibrary(option: LibraryOption): void {
  const entry: Recent = {
    id: option.id,
    ...(option.title && { title: option.title }),
    ...(option.logo !== undefined && { logo: option.logo }),
  };
  const next = [entry, ...readRecent().filter((r) => r.id !== option.id)].slice(0, RECENT_MAX);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // Storage is off or full: the picker works without its Recent group.
  }
}

const ownerOf = (id: string) => id.split("/").filter(Boolean)[0] ?? id;
const repoOf = (id: string) => id.split("/").filter(Boolean)[1] ?? id;

/** The title, when it says more than the repository's name. */
const titleOf = ({ id, title }: LibraryOption) =>
  title && ![id, repoOf(id)].some((same) => same.toLowerCase() === title.toLowerCase())
    ? title
    : undefined;

const matches = (option: LibraryOption, text: string) => {
  const needle = text.toLowerCase();
  return (
    option.id.toLowerCase().includes(needle) ||
    (option.title?.toLowerCase().includes(needle) ?? false)
  );
};

/** The text after it has rested for `ms`. */
function useDebounced(text: string, ms: number): string {
  const [rested, setRested] = useState(text);
  useEffect(() => {
    const timer = setTimeout(() => setRested(text), ms);
    return () => clearTimeout(timer);
  }, [text, ms]);
  return rested;
}

/** Asks nothing: a stand-in while there is no `query` or the list has never opened. */
const IDLE: LibraryChoicesQuery = {
  queryKey: ["library-combobox", "idle"],
  queryFn: () => ({ options: [] }),
  enabled: false,
};

export function LibraryCombobox<K extends QueryKey>(props: LibraryComboboxProps<K>) {
  const {
    label,
    variant = "field",
    placeholder,
    hint,
    options: given,
    loading = false,
    failed = false,
    onRetry,
    query,
    custom,
    children,
    className,
  } = props;
  const t = useMessages(messages).libraryPicker;
  const c = useMessages(common);
  const uid = useId();
  const triggerId = props.id ?? `${uid}-trigger`;
  const [open, setOpen] = useState(false);
  // Once opened, a `query` stays live (cached), so reopening shows the list at once.
  const [opened, setOpened] = useState(false);
  const [text, setText] = useState("");
  const [active, setActive] = useState("");
  // cmdk names the highlighted row in `aria-activedescendant` only once the highlight moves; until
  // then a screen reader would hear nothing on opening. Point at the highlighted row whenever it
  // changes.
  const root = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    const sync = () => {
      const input = node.querySelector("[cmdk-input]");
      const row = node.querySelector('[cmdk-item][aria-selected="true"]');
      if (!input) return;
      if (row?.id) {
        if (input.getAttribute("aria-activedescendant") !== row.id) {
          input.setAttribute("aria-activedescendant", row.id);
        }
      } else if (input.hasAttribute("aria-activedescendant")) {
        input.removeAttribute("aria-activedescendant");
      }
    };
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(node, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["aria-selected"],
    });
    return () => observer.disconnect();
  }, []);
  const [recent, setRecent] = useState<Recent[]>(readRecent);
  const rested = useDebounced(text.trim(), DEBOUNCE_MS);
  // The feature's key type only matters to the feature: here any key will do.
  const asked = (query && opened ? query(rested) : undefined) as LibraryChoicesQuery | undefined;
  const fetched = useQuery(
    asked ? { ...asked, placeholderData: keepPreviousData, retry: false } : IDLE,
  );

  const chosen = props.multiple ? props.value : props.value ? [props.value] : [];
  const picked = new Set(chosen);

  const onOpenChange = useCallback((next: boolean) => {
    setOpen(next);
    if (next) {
      setOpened(true);
      setRecent(readRecent());
    } else {
      setText("");
      setActive("");
    }
  }, []);

  const typed = text.trim();
  const status: "pending" | "error" | "ready" = !query
    ? failed
      ? "error"
      : loading || !given
        ? "pending"
        : "ready"
    : fetched.isError
      ? "error"
      : fetched.data
        ? "ready"
        : "pending";
  // While a new text is asked for, the last answer is filtered here so the list follows the keys.
  // Static options are filtered here; a query's are, too, while its answer is for older text.
  const local = !query || fetched.isPlaceholderData || rested !== typed;
  const all = useMemo(() => {
    const list = (query ? fetched.data?.options : given) ?? [];
    return local && typed ? list.filter((o) => matches(o, typed)) : list;
  }, [query, given, fetched.data, local, typed]);
  const total = local ? undefined : fetched.data?.total;
  const known = useMemo(() => new Map(all.map((o) => [o.id, o])), [all]);
  // Every library is in the list: a recent one missing from it is gone (or not offered here).
  const complete = !typed && status === "ready" && (!query || (total ?? 0) <= all.length);
  const recents = typed
    ? []
    : recent.filter((r) => !complete || known.has(r.id)).map((r) => known.get(r.id) ?? r);
  // A library chosen but not in the list (a removed one, or past the first page) is still shown.
  const extra: LibraryOption[] = typed
    ? []
    : chosen
        .filter((id) => !known.has(id) && !recents.some((r) => r.id === id))
        .map((id) => ({ id }));
  const offerTyped =
    custom !== undefined &&
    typed !== "" &&
    custom(typed) &&
    !known.has(typed) &&
    !picked.has(typed);
  const grouped = all.length > GROUP_FROM;
  const groups = useMemo(() => {
    if (!grouped) return [];
    const byOwner = new Map<string, LibraryOption[]>();
    for (const option of all) {
      const owner = ownerOf(option.id);
      byOwner.set(owner, [...(byOwner.get(owner) ?? []), option]);
    }
    return [...byOwner.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [all, grouped]);

  const choose = (option: LibraryOption) => {
    if (props.multiple) {
      if (picked.has(option.id)) {
        props.onChange(props.value.filter((id) => id !== option.id));
        return;
      }
      // Stored for the next opening; the open list keeps its order under the pointer.
      rememberLibrary(option);
      props.onChange([...props.value, option.id]);
      return;
    }
    rememberLibrary(option);
    props.onChange(option.id);
    onOpenChange(false);
  };
  const clear = () => {
    if (props.multiple) props.onChange([]);
    else {
      props.onChange(undefined);
      onOpenChange(false);
    }
  };

  const row = (option: LibraryOption, key: string) => {
    const on = picked.has(option.id);
    const title = titleOf(option);
    return (
      <CommandItem
        key={key}
        value={key}
        aria-checked={on}
        onSelect={() => choose(option)}
        className="gap-2.5"
      >
        {props.multiple && <Box checked={on} />}
        <LibraryMark id={option.id} logo={option.logo} size="sm" />
        <span className="flex min-w-0 flex-1 items-baseline gap-2">
          <span className="min-w-0 truncate font-mono text-mono">{option.id}</span>
          {title && " "}
          {title && (
            <span className="min-w-0 shrink-[2] truncate text-small text-muted-foreground">
              {title}
            </span>
          )}
        </span>
        {option.detail !== undefined && (
          <span className="num ml-auto shrink-0 text-small text-muted-foreground">
            <span aria-hidden={option.detailLabel ? true : undefined}>{option.detail}</span>
            {option.detailLabel && <span className="sr-only">, {option.detailLabel}</span>}
          </span>
        )}
        {!props.multiple && (
          <Check
            aria-hidden="true"
            className={cn("ml-auto size-4 text-foreground!", !on && "invisible")}
          />
        )}
      </CommandItem>
    );
  };

  const count = all.length + extra.length;
  // The highlighted row (cmdk's value): kept while it is still listed, else the chosen library's
  // row, else the first one, so the input always has an active descendant to announce.
  const keys = [
    ...(offerTyped ? [`custom ${typed}`] : []),
    ...recents.map((o) => `recent ${o.id}`),
    ...extra.map((o) => `extra ${o.id}`),
    ...(grouped ? groups.flatMap(([, items]) => items) : all).map((o) => o.id),
  ];
  const single = !props.multiple ? props.value : undefined;
  const activeKey = keys.includes(active)
    ? active
    : ((single && keys.find((k) => k === single || k.endsWith(` ${single}`))) ?? keys[0] ?? "");
  const announce =
    status === "pending"
      ? t.loading
      : status === "error"
        ? t.failed
        : count === 0 && !offerTyped
          ? typed
            ? t.noMatch(typed)
            : t.none
          : t.found(count + (offerTyped ? 1 : 0));

  const list = (
    // cmdk names its input with a hidden label of its own (`aria-labelledby`), from `label`.
    <Command
      ref={root}
      shouldFilter={false}
      label={t.find}
      value={activeKey}
      onValueChange={setActive}
    >
      <CommandInput value={text} onValueChange={setText} placeholder={t.findPlaceholder} />
      <p role="status" className="sr-only">
        {open ? announce : ""}
      </p>
      {status === "pending" && (
        <div aria-hidden="true" className="space-y-1 p-2">
          {["w-40", "w-32", "w-44"].map((w) => (
            <div key={w} className="flex h-11 items-center gap-2.5 px-2 fine:h-8">
              <Skeleton className="size-6 rounded-md" />
              <Skeleton className={cn("h-3.5", w)} />
            </div>
          ))}
        </div>
      )}
      {status === "error" && (
        <div role="alert" className="flex flex-col items-start gap-2 p-3 text-body">
          <p className="flex items-center gap-2 text-destructive-ink">
            <CircleAlert aria-hidden="true" data-icon-motion="alert" className="size-4" />
            {t.failed}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => (query ? void fetched.refetch() : onRetry?.())}
          >
            {c.retry}
          </Button>
        </div>
      )}
      {status === "ready" && (
        <CommandList
          label={label}
          aria-multiselectable={props.multiple || undefined}
          aria-busy={(query && fetched.isFetching) || undefined}
        >
          {offerTyped && (
            <CommandGroup>
              <CommandItem
                value={`custom ${typed}`}
                onSelect={() => choose({ id: typed })}
                className="gap-2.5"
              >
                <Plus aria-hidden="true" data-icon-motion="turn" />
                <span className="min-w-0 truncate">
                  {t.typedChoice(<span className="font-mono text-mono">{typed}</span>)}
                </span>
              </CommandItem>
            </CommandGroup>
          )}
          {recents.length > 0 && (
            <CommandGroup heading={t.recent}>
              {recents.map((option) => row(option, `recent ${option.id}`))}
            </CommandGroup>
          )}
          {extra.length > 0 && (
            <CommandGroup>{extra.map((option) => row(option, `extra ${option.id}`))}</CommandGroup>
          )}
          {grouped
            ? groups.map(([owner, items]) => (
                <CommandGroup key={owner} heading={owner}>
                  {items.map((option) => row(option, option.id))}
                </CommandGroup>
              ))
            : all.length > 0 && (
                <CommandGroup heading={recents.length > 0 ? t.all : undefined}>
                  {all.map((option) => row(option, option.id))}
                </CommandGroup>
              )}
          {count === 0 && !offerTyped && (
            <p
              role="presentation"
              className="px-2 py-6 text-center text-body text-muted-foreground"
            >
              {typed ? t.noMatch(typed) : t.none}
            </p>
          )}
          {chosen.length > 0 && (
            <>
              <CommandSeparator />
              <CommandGroup>
                <CommandItem value="__clear__" onSelect={clear} className="justify-center">
                  {t.clear}
                </CommandItem>
              </CommandGroup>
            </>
          )}
        </CommandList>
      )}
      {status === "ready" && total !== undefined && total > all.length && (
        <p className="border-t border-rule px-3 py-2 text-small text-muted-foreground">
          {t.partial(all.length, total)}
        </p>
      )}
    </Command>
  );

  const singleOption = single ? (known.get(single) ?? { id: single }) : undefined;

  const triggerNode =
    children ??
    (variant === "filter" ? (
      <Button
        id={triggerId}
        variant="outline"
        size="sm"
        aria-label={
          chosen.length === 0
            ? label
            : props.multiple
              ? `${label}: ${t.selected(chosen.length)}`
              : `${label}: ${single}`
        }
        className={cn("max-w-full", chosen.length > 0 && "border-muted-foreground/50")}
      >
        <ListFilter aria-hidden="true" data-icon-motion="tilt" />
        {label}
        {singleOption && (
          <span className="flex min-w-0 items-center gap-1.5 border-l border-rule pl-2">
            <LibraryMark id={singleOption.id} logo={singleOption.logo} size="sm" />
            <span className="max-w-40 truncate font-mono text-mono">{singleOption.id}</span>
          </span>
        )}
        {props.multiple && chosen.length > 0 && (
          <span className="border-l border-rule pl-2 text-muted-foreground">
            {t.selected(chosen.length)}
          </span>
        )}
      </Button>
    ) : (
      <button
        id={triggerId}
        type="button"
        aria-labelledby={`${uid}-label ${triggerId}`}
        className={cn(triggerRecipe, "w-full")}
      >
        <span className="flex min-w-0 items-center gap-2">
          {singleOption ? (
            <>
              <LibraryMark id={singleOption.id} logo={singleOption.logo} size="sm" />
              <span className="truncate font-mono text-mono">{singleOption.id}</span>
            </>
          ) : props.multiple && chosen.length > 0 ? (
            <span className="truncate">{t.selected(chosen.length)}</span>
          ) : (
            <span className="truncate text-muted-foreground">{placeholder ?? t.choose}</span>
          )}
        </span>
        <ChevronsUpDown aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
      </button>
    ));

  const popover = (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>{triggerNode}</PopoverTrigger>
      <PopoverContent className="w-[min(24rem,calc(100vw-2rem))] min-w-(--radix-popover-trigger-width) p-0">
        {list}
      </PopoverContent>
    </Popover>
  );

  if (variant === "filter" || children) {
    return <div className={cn("min-w-0", className)}>{popover}</div>;
  }
  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      <span id={`${uid}-label`} className="text-body font-medium">
        {label}
      </span>
      {popover}
      {hint && <p className="text-small text-muted-foreground">{hint}</p>}
      {props.multiple && props.value.length > 0 && (
        <TagList label={t.chosen}>
          {props.value.map((id) => {
            const option = known.get(id) ?? recent.find((r) => r.id === id) ?? { id };
            return (
              <li key={id} className="reveal flex min-w-0">
                <Tag
                  mono
                  leading={<LibraryMark id={id} logo={option.logo} size="sm" className="size-5" />}
                  removeLabel={t.remove(id)}
                  onRemove={() => props.onChange(props.value.filter((v) => v !== id))}
                  className="pl-1.5"
                >
                  {id}
                </Tag>
              </li>
            );
          })}
        </TagList>
      )}
    </div>
  );
}

/** A multiple choice's tick box, as in the faceted filters. */
function Box({ checked }: { checked: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex size-4 flex-none items-center justify-center rounded-sm border transition-colors duration-(--dur-fast)",
        checked
          ? "border-selection bg-selection text-route-foreground"
          : "border-muted-foreground bg-background",
      )}
    >
      {checked && <Check className="size-3! text-route-foreground!" strokeWidth={3} />}
    </span>
  );
}
