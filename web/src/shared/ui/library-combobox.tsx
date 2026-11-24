import {
  keepPreviousData,
  type QueryKey,
  type UseQueryOptions,
  useQuery,
} from "@tanstack/react-query";
import { Check, ChevronsUpDown, CircleAlert, ListFilter, Plus } from "lucide-react";
import type * as React from "react";
import { type ReactNode, useCallback, useEffect, useId, useState } from "react";
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

/**
 * cmdk names the highlighted row in `aria-activedescendant` only once the highlight moves; until
 * then a screen reader would hear nothing on opening. This ref points the input at the highlighted
 * row whenever it changes.
 */
function useActiveDescendant() {
  return useCallback((node: HTMLDivElement | null) => {
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
}

type Status = "pending" | "error" | "ready";

interface Source {
  status: Status;
  /** The libraries that match the text, in the API's order. */
  all: readonly LibraryOption[];
  /** Every match, when `all` was cut short. */
  total: number | undefined;
  /** The list is every library there is to offer (no text, not cut short). */
  complete: boolean;
  fetching: boolean;
  retry: () => void;
}

/** The libraries to show for the text: the feature's `options`, or its `query` once opened. */
function useSource<K extends QueryKey>(
  props: LibraryComboboxProps<K>,
  opened: boolean,
  typed: string,
): Source {
  const rested = useDebounced(typed, DEBOUNCE_MS);
  // The feature's key type only matters to the feature: here any key will do.
  const asked = (props.query && opened ? props.query(rested) : undefined) as
    | LibraryChoicesQuery
    | undefined;
  const fetched = useQuery(
    asked ? { ...asked, placeholderData: keepPreviousData, retry: false } : IDLE,
  );
  if (!props.query) return fromOptions(props, typed);
  // While the answer is for older text, it is filtered here so the list follows the keys.
  const local = fetched.isPlaceholderData || rested !== typed;
  return finish(
    {
      status: statusOf(fetched.isError, fetched.data !== undefined),
      all: filtered(fetched.data?.options ?? [], local ? typed : ""),
      total: local ? undefined : fetched.data?.total,
      fetching: fetched.isFetching,
      retry: () => void fetched.refetch(),
    },
    typed,
  );
}

const statusOf = (failed: boolean, ready: boolean): Status =>
  failed ? "error" : ready ? "ready" : "pending";

const filtered = (list: readonly LibraryOption[], text: string) =>
  text ? list.filter((o) => matches(o, text)) : list;

/** Options the feature passed, with its own loading and failure. */
function fromOptions<K extends QueryKey>(props: LibraryComboboxProps<K>, typed: string): Source {
  const { options, loading = false, failed = false, onRetry } = props;
  return finish(
    {
      status: statusOf(failed, !loading && options !== undefined),
      all: filtered(options ?? [], typed),
      total: undefined,
      fetching: false,
      retry: () => onRetry?.(),
    },
    typed,
  );
}

function finish(source: Omit<Source, "complete">, typed: string): Source {
  const complete = !typed && source.status === "ready" && (source.total ?? 0) <= source.all.length;
  return { ...source, complete };
}

interface Arranged {
  recents: LibraryOption[];
  /** Chosen libraries the list does not hold (a removed one, or past the first page). */
  extra: LibraryOption[];
  /** The typed text, offered as itself. */
  typedChoice: string | undefined;
  /** By owner (more than 20), else one group. */
  groups: [owner: string | undefined, items: LibraryOption[]][];
  /** Every row's key, top to bottom (cmdk's values). */
  keys: string[];
}

function byOwner(all: readonly LibraryOption[]): Arranged["groups"] {
  if (all.length === 0) return [];
  if (all.length <= GROUP_FROM) return [[undefined, [...all]]];
  const owners = new Map<string, LibraryOption[]>();
  for (const option of all) {
    const owner = ownerOf(option.id);
    owners.set(owner, [...(owners.get(owner) ?? []), option]);
  }
  return [...owners.entries()].sort(([a], [b]) => a.localeCompare(b));
}

/** The rows in the order they are shown: typed, Recent, chosen elsewhere, then the libraries. */
function arrange(
  source: Source,
  recent: readonly Recent[],
  chosen: readonly string[],
  typed: string,
  custom: ((text: string) => boolean) | undefined,
): Arranged {
  const known = new Map(source.all.map((o) => [o.id, o]));
  // With every library in the list, a recent one missing from it is gone (or not offered here).
  const recents = typed
    ? []
    : recent
        .filter((r) => !source.complete || known.has(r.id))
        .map((r): LibraryOption => known.get(r.id) ?? r);
  const extra = typed
    ? []
    : chosen
        .filter((id) => !known.has(id) && !recents.some((r) => r.id === id))
        .map((id) => ({ id }));
  const typedChoice =
    custom && typed && custom(typed) && !known.has(typed) && !chosen.includes(typed)
      ? typed
      : undefined;
  const groups = byOwner(source.all);
  const keys = [
    ...(typedChoice ? [`custom ${typedChoice}`] : []),
    ...recents.map((o) => `recent ${o.id}`),
    ...extra.map((o) => `extra ${o.id}`),
    ...groups.flatMap(([, items]) => items.map((o) => o.id)),
  ];
  return { recents, extra, typedChoice, groups, keys };
}

/** The highlighted row: the one kept while it is listed, else the chosen one's, else the first. */
function activeOf(keys: readonly string[], active: string, single: string | undefined): string {
  if (keys.includes(active)) return active;
  const chosen = single && keys.find((k) => k === single || k.endsWith(` ${single}`));
  return chosen || (keys[0] ?? "");
}

function OptionRow({
  option,
  value,
  on,
  multiple,
  onSelect,
}: {
  option: LibraryOption;
  value: string;
  on: boolean;
  multiple: boolean;
  onSelect: () => void;
}) {
  const title = titleOf(option);
  return (
    <CommandItem value={value} aria-checked={on} onSelect={onSelect} className="gap-2.5">
      {multiple && <Box checked={on} />}
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
      {option.detail !== undefined && <Detail option={option} />}
      {!multiple && (
        <Check
          aria-hidden="true"
          className={cn("ml-auto size-4 text-foreground!", !on && "invisible")}
        />
      )}
    </CommandItem>
  );
}

/** A row's count at its end, read out in words. */
function Detail({ option }: { option: LibraryOption }) {
  return (
    <span className="num ml-auto shrink-0 text-small text-muted-foreground">
      <span aria-hidden={option.detailLabel ? true : undefined}>{option.detail}</span>
      {option.detailLabel && <span className="sr-only">, {option.detailLabel}</span>}
    </span>
  );
}

/** What the live line says: loading, failed, nothing, or how many match. */
function useAnnouncement(source: Source, rows: Arranged, typed: string): string {
  const t = useMessages(messages).libraryPicker;
  if (source.status === "pending") return t.loading;
  if (source.status === "error") return t.failed;
  const count = source.all.length + rows.extra.length + (rows.typedChoice ? 1 : 0);
  if (count > 0) return t.found(count);
  return typed ? t.noMatch(typed) : t.none;
}

/** Loading (skeleton rows) and failed (a sentence and Try again) in place of the list. */
function ListStates({ source }: { source: Source }) {
  const t = useMessages(messages).libraryPicker;
  const c = useMessages(common);
  if (source.status === "pending") {
    return (
      <div aria-hidden="true" className="space-y-1 p-2">
        {["w-40", "w-32", "w-44"].map((w) => (
          <div key={w} className="flex h-11 items-center gap-2.5 px-2 fine:h-8">
            <Skeleton className="size-6 rounded-md" />
            <Skeleton className={cn("h-3.5", w)} />
          </div>
        ))}
      </div>
    );
  }
  if (source.status === "error") {
    return (
      <div role="alert" className="flex flex-col items-start gap-2 p-3 text-body">
        <p className="flex items-center gap-2 text-destructive-ink">
          <CircleAlert aria-hidden="true" data-icon-motion="alert" className="size-4" />
          {t.failed}
        </p>
        <Button variant="outline" size="sm" onClick={source.retry}>
          {c.retry}
        </Button>
      </div>
    );
  }
  return null;
}

/** The typed value offered as itself ("Use /gone/lib"). */
function TypedChoice({ id, onChoose }: { id: string; onChoose: (option: LibraryOption) => void }) {
  const t = useMessages(messages).libraryPicker;
  return (
    <CommandGroup>
      <CommandItem value={`custom ${id}`} onSelect={() => onChoose({ id })} className="gap-2.5">
        <Plus aria-hidden="true" data-icon-motion="turn" />
        <span className="min-w-0 truncate">
          {t.typedChoice(<span className="font-mono text-mono">{id}</span>)}
        </span>
      </CommandItem>
    </CommandGroup>
  );
}

/** The rows in their groups: the typed value, Recent, chosen elsewhere, then the libraries. */
function ChoiceGroups({
  rows,
  row,
  onChoose,
}: {
  rows: Arranged;
  row: (option: LibraryOption, key: string) => ReactNode;
  onChoose: (option: LibraryOption) => void;
}) {
  const t = useMessages(messages).libraryPicker;
  const recent = rows.recents.length > 0;
  return (
    <>
      {rows.typedChoice && <TypedChoice id={rows.typedChoice} onChoose={onChoose} />}
      {recent && (
        <CommandGroup heading={t.recent}>
          {rows.recents.map((option) => row(option, `recent ${option.id}`))}
        </CommandGroup>
      )}
      {rows.extra.length > 0 && (
        <CommandGroup>{rows.extra.map((option) => row(option, `extra ${option.id}`))}</CommandGroup>
      )}
      {rows.groups.map(([owner, items]) => (
        <CommandGroup key={owner ?? ""} heading={owner ?? (recent ? t.all : undefined)}>
          {items.map((option) => row(option, option.id))}
        </CommandGroup>
      ))}
    </>
  );
}

/** Under a list the API cut short: how much is shown, and to type to narrow it. */
function PartialNote({ source }: { source: Source }) {
  const t = useMessages(messages).libraryPicker;
  if (source.status !== "ready" || (source.total ?? 0) <= source.all.length) return null;
  return (
    <p className="border-t border-rule px-3 py-2 text-small text-muted-foreground">
      {t.partial(source.all.length, source.total ?? 0)}
    </p>
  );
}

/** Nothing to list: no library matches the text, or there are none. */
function NothingListed({ typed }: { typed: string }) {
  const t = useMessages(messages).libraryPicker;
  return (
    <p role="presentation" className="px-2 py-6 text-center text-body text-muted-foreground">
      {typed ? t.noMatch(typed) : t.none}
    </p>
  );
}

/** Clear at the list's end, while something is chosen. */
function ClearRow({ onClear }: { onClear: () => void }) {
  const t = useMessages(messages).libraryPicker;
  return (
    <>
      <CommandSeparator />
      <CommandGroup>
        <CommandItem value="__clear__" onSelect={onClear} className="justify-center">
          {t.clear}
        </CommandItem>
      </CommandGroup>
    </>
  );
}

interface ChoicesProps {
  label: string;
  multiple: boolean;
  open: boolean;
  source: Source;
  rows: Arranged;
  chosen: readonly string[];
  single: string | undefined;
  text: string;
  onText: (text: string) => void;
  onChoose: (option: LibraryOption) => void;
  onClear: () => void;
}

/** The popover's content: the text box, the live line, the states and the list. */
function Choices({
  label,
  multiple,
  open,
  source,
  rows,
  chosen,
  single,
  text,
  onText,
  onChoose,
  onClear,
}: ChoicesProps) {
  const t = useMessages(messages).libraryPicker;
  const root = useActiveDescendant();
  const [active, setActive] = useState("");
  const typed = text.trim();
  const announce = useAnnouncement(source, rows, typed);
  const picked = new Set(chosen);
  const row = (option: LibraryOption, key: string) => (
    <OptionRow
      key={key}
      value={key}
      option={option}
      on={picked.has(option.id)}
      multiple={multiple}
      onSelect={() => onChoose(option)}
    />
  );
  return (
    // cmdk names its input with a hidden label of its own (`aria-labelledby`), from `label`.
    <Command
      ref={root}
      shouldFilter={false}
      label={t.find}
      value={activeOf(rows.keys, active, single)}
      onValueChange={setActive}
    >
      <CommandInput value={text} onValueChange={onText} placeholder={t.findPlaceholder} />
      <p role="status" className="sr-only">
        {open ? announce : ""}
      </p>
      <ListStates source={source} />
      {source.status === "ready" && (
        <CommandList
          label={label}
          aria-multiselectable={multiple || undefined}
          aria-busy={source.fetching || undefined}
        >
          <ChoiceGroups rows={rows} row={row} onChoose={onChoose} />
          {rows.keys.length === 0 && <NothingListed typed={typed} />}
          {chosen.length > 0 && <ClearRow onClear={onClear} />}
        </CommandList>
      )}
      <PartialNote source={source} />
    </Command>
  );
}

interface TriggerProps extends React.ComponentProps<"button"> {
  id: string;
  chosen: readonly string[];
  /** The single chosen library. */
  shown: LibraryOption | undefined;
}

/** The toolbar trigger: an outline button naming the filter and what it holds. */
function FilterTrigger({ id, label, chosen, shown, ...rest }: TriggerProps & { label: string }) {
  const t = useMessages(messages).libraryPicker;
  const value = shown?.id ?? (chosen.length > 0 ? t.selected(chosen.length) : "");
  return (
    <Button
      {...rest}
      id={id}
      variant="outline"
      size="sm"
      aria-label={value ? `${label}: ${value}` : label}
      className={cn("max-w-full", value && "border-muted-foreground/50")}
    >
      <ListFilter aria-hidden="true" data-icon-motion="tilt" />
      {label}
      {value && (
        <span className="flex min-w-0 items-center gap-1.5 border-l border-rule pl-2">
          {shown && <LibraryMark id={shown.id} logo={shown.logo} size="sm" />}
          <span className={cn("max-w-40 truncate", shown && "font-mono text-mono")}>{value}</span>
        </span>
      )}
    </Button>
  );
}

/** A field's trigger: a control-like box with the choice (or the placeholder) and a chevron. */
function FieldTrigger({
  id,
  labelId,
  chosen,
  shown,
  placeholder,
  ...rest
}: TriggerProps & { labelId: string; placeholder: string | undefined }) {
  const t = useMessages(messages).libraryPicker;
  const fallback = placeholder ?? t.choose;
  const text = shown?.id ?? (chosen.length > 0 ? t.selected(chosen.length) : fallback);
  return (
    <button
      {...rest}
      id={id}
      type="button"
      aria-labelledby={`${labelId} ${id}`}
      className={cn(triggerRecipe, "w-full")}
    >
      <span className="flex min-w-0 items-center gap-2">
        {shown && <LibraryMark id={shown.id} logo={shown.logo} size="sm" />}
        <span
          className={cn(
            "truncate",
            shown && "font-mono text-mono",
            chosen.length === 0 && "text-muted-foreground",
          )}
        >
          {text}
        </span>
      </span>
      <ChevronsUpDown aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
    </button>
  );
}

/** A field's chosen libraries as removable chips. */
function ChosenTags({
  ids,
  find,
  onChange,
}: {
  ids: readonly string[];
  find: (id: string) => LibraryOption | undefined;
  onChange: (ids: string[]) => void;
}) {
  const t = useMessages(messages).libraryPicker;
  if (ids.length === 0) return null;
  return (
    <TagList label={t.chosen}>
      {ids.map((id) => (
        <li key={id} className="reveal flex min-w-0">
          <Tag
            mono
            leading={<LibraryMark id={id} logo={find(id)?.logo} size="sm" className="size-5" />}
            removeLabel={t.remove(id)}
            onRemove={() => onChange(ids.filter((v) => v !== id))}
            className="pl-1.5"
          >
            {id}
          </Tag>
        </li>
      ))}
    </TagList>
  );
}

/** What the picker holds and how a pick changes it, single or multiple. */
function useChoice<K extends QueryKey>(props: LibraryComboboxProps<K>, close: () => void) {
  const chosen: readonly string[] = props.multiple ? props.value : props.value ? [props.value] : [];
  const choose = (option: LibraryOption) => {
    if (!props.multiple) {
      rememberLibrary(option);
      props.onChange(option.id);
      close();
      return;
    }
    if (props.value.includes(option.id)) {
      props.onChange(props.value.filter((id) => id !== option.id));
      return;
    }
    // Stored for the next opening; the open list keeps its order under the pointer.
    rememberLibrary(option);
    props.onChange([...props.value, option.id]);
  };
  const clear = () => {
    if (props.multiple) {
      props.onChange([]);
      return;
    }
    props.onChange(undefined);
    close();
  };
  return { chosen, single: props.multiple ? undefined : props.value, choose, clear };
}

export function LibraryCombobox<K extends QueryKey>(props: LibraryComboboxProps<K>) {
  const { label, variant = "field", placeholder, hint, custom, children, className } = props;
  const uid = useId();
  const [open, setOpen] = useState(false);
  // Once opened, a `query` stays live (cached), so reopening shows the list at once.
  const [opened, setOpened] = useState(false);
  const [text, setText] = useState("");
  const [recent, setRecent] = useState<Recent[]>(readRecent);
  const typed = text.trim();
  const source = useSource(props, opened, typed);
  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setText("");
      return;
    }
    setOpened(true);
    setRecent(readRecent());
  };
  const { chosen, single, choose, clear } = useChoice(props, () => onOpenChange(false));
  const rows = arrange(source, recent, chosen, typed, custom);
  const find = (id: string) =>
    source.all.find((o) => o.id === id) ?? recent.find((r) => r.id === id);
  const triggerProps = {
    id: props.id ?? `${uid}-trigger`,
    chosen,
    shown: single ? (find(single) ?? { id: single }) : undefined,
  };
  const trigger =
    children ??
    (variant === "filter" ? (
      <FilterTrigger {...triggerProps} label={label} />
    ) : (
      <FieldTrigger {...triggerProps} labelId={`${uid}-label`} placeholder={placeholder} />
    ));

  const popover = (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent className="w-[min(24rem,calc(100vw-2rem))] min-w-(--radix-popover-trigger-width) p-0">
        <Choices
          label={label}
          multiple={props.multiple === true}
          open={open}
          source={source}
          rows={rows}
          chosen={chosen}
          single={single}
          text={text}
          onText={setText}
          onChoose={choose}
          onClear={clear}
        />
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
      {props.multiple && <ChosenTags ids={props.value} find={find} onChange={props.onChange} />}
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
