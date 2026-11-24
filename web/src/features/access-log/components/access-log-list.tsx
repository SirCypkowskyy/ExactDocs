import { useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import {
  ArrowRight,
  ArrowRightLeft,
  CalendarRange,
  ListFilter,
  type LucideIcon,
  Plus,
  ScrollText,
  Trash2,
  UserCheck,
  UserMinus,
  UserPen,
  UserRound,
  Users,
} from "lucide-react";
import { useId, useMemo } from "react";
import { type Language, useLanguage, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Badge, type BadgeTone } from "@/shared/ui/badge";
import { LibraryCell, Person, RelativeTime } from "@/shared/ui/data-table/cells";
import { DataTable } from "@/shared/ui/data-table/data-table";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import type { RowAction } from "@/shared/ui/data-table/row-actions";
import { SearchFilter } from "@/shared/ui/data-table/search-filter";
import type { ServerSource } from "@/shared/ui/data-table/server-pages";
import type { TableConfig } from "@/shared/ui/data-table/table-search";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import {
  type TableFilter,
  type TableParam,
  useDataTable,
} from "@/shared/ui/data-table/use-data-table";
import { LibraryCombobox } from "@/shared/ui/library-combobox";
import { filterLibrariesQueryOptions } from "../api/access-log-query";
import { messages } from "../messages";
import {
  type AccessEvent,
  type AccessLogView,
  CHANGES,
  type Change,
  describeEvent,
  explainAccessLogError,
  isLibraryId,
  parseRange,
  rangeLabel,
  WHEN_PRESETS,
} from "../model/access-log";
import { CustomDates } from "./when-filter";

/*
 * The access log as a table (blocks-map §2.3, "Access log"): who changed access, how and when,
 * newest first unless sorted by another header (when, library, change), numbered pages by offset,
 * and the filters in the URL: the changes, who made them, whom they were about, when (a preset or
 * custom days) and, for operators, the library. A new sort starts from page 1 with a new request,
 * since a cursor is made for one sort. On a phone each row is a card titled by the event's sentence.
 */

type Messages = (typeof messages)["en"];
type ChangeLook = { icon: LucideIcon; tone: BadgeTone };

const CHANGE_LOOKS: Record<Change | "changed", ChangeLook> = {
  granted: { icon: UserCheck, tone: "neutral" },
  changed: { icon: UserPen, tone: "neutral" },
  revoked: { icon: UserMinus, tone: "neutral" },
  ownership_transferred: { icon: ArrowRightLeft, tone: "neutral" },
  library_created: { icon: Plus, tone: "neutral" },
  library_deleted: { icon: Trash2, tone: "destructive" },
};

/** A grant that replaced a role reads as a change, not as a new role. */
const lookOf = (event: AccessEvent) =>
  event.change === "granted" && event.previous_role ? "changed" : event.change;

const sentenceOf = (event: AccessEvent, language: ReturnType<typeof useLanguage>) =>
  describeEvent(event, language)
    .map((p) => p.text)
    .join("");

function EventSentence({ event }: { event: AccessEvent }) {
  const language = useLanguage();
  return (
    <span className="block [overflow-wrap:anywhere]">
      {describeEvent(event, language).map((part) => (
        <span
          key={part.key}
          className={cn(
            part.kind === "person" && "font-medium",
            part.kind === "group" && "font-mono text-small font-medium",
            part.kind === "role" && "rounded-sm bg-accent px-1.5 py-0.5 text-small",
          )}
        >
          {part.text}
        </span>
      ))}
    </span>
  );
}

function ChangeBadge({ event }: { event: AccessEvent }) {
  const t = useMessages(messages).list;
  const look = lookOf(event);
  const { icon: Icon, tone } = CHANGE_LOOKS[look];
  return (
    <Badge tone={tone}>
      <Icon aria-hidden="true" className="size-3" />
      {t.change[look]}
    </Badge>
  );
}

function Subject({ event }: { event: AccessEvent }) {
  if (!event.subject) return <span className="text-muted-foreground">–</span>;
  if (event.kind !== "group") return <Person name={event.subject} />;
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="inline-flex size-6 flex-none items-center justify-center rounded-full bg-secondary text-muted-foreground">
        <Users aria-hidden="true" className="size-3.5" />
      </span>
      <span className="font-mono text-mono [overflow-wrap:anywhere]">{event.subject}</span>
    </span>
  );
}

/** "viewer → admin" on screen, "from viewer to admin" for a screen reader. */
function RoleChange({ event }: { event: AccessEvent }) {
  const t = useMessages(messages);
  if (!event.role) return <span className="text-muted-foreground">–</span>;
  const name = (role: string) => t.sentence.roles[role] ?? role;
  if (!event.previous_role) return <span>{name(event.role)}</span>;
  const from = name(event.previous_role);
  const to = name(event.role);
  return (
    <span className="whitespace-nowrap">
      <span aria-hidden="true" className="inline-flex items-center gap-1">
        <span className="text-muted-foreground">{from}</span>
        <ArrowRight className="size-3.5 text-muted-foreground" />
        {to}
      </span>
      <span className="sr-only">{t.list.fromTo(from, to)}</span>
    </span>
  );
}

function Actor({ event }: { event: AccessEvent }) {
  const t = useMessages(messages).sentence;
  if (event.actor) return <Person name={event.actor} />;
  return <span className="text-muted-foreground">{t.instance}</span>;
}

// Built once per language (and log): a cell is rendered as a component, so a new function would
// remount it. The API sorts by when, library and change.
const columnsOf = (t: Messages, everyLibrary: boolean): ColumnDef<AccessEvent>[] => [
  {
    // The sentence titles a phone's card; on a wider screen the columns below say the same.
    id: "event",
    header: t.list.columns.event,
    enableSorting: false,
    enableHiding: false,
    meta: { priority: 1, className: "hidden" },
    cell: ({ row }) => <EventSentence event={row.original} />,
  },
  {
    accessorKey: "at",
    header: t.list.columns.when,
    sortDescFirst: true,
    enableHiding: false,
    meta: { priority: 2 },
    cell: ({ row }) => <RelativeTime iso={row.original.at} />,
  },
  ...(everyLibrary
    ? [
        {
          accessorKey: "library",
          header: t.list.columns.library,
          meta: { priority: 3, skeleton: "avatar" },
          cell: ({ row }) => <LibraryCell id={row.original.library} />,
        } satisfies ColumnDef<AccessEvent>,
      ]
    : []),
  {
    accessorKey: "change",
    header: t.list.columns.change,
    meta: { skeleton: "pill" },
    cell: ({ row }) => <ChangeBadge event={row.original} />,
  },
  {
    accessorKey: "subject",
    header: t.list.columns.subject,
    enableSorting: false,
    meta: { skeleton: "avatar" },
    cell: ({ row }) => <Subject event={row.original} />,
  },
  {
    accessorKey: "role",
    header: t.list.columns.role,
    enableSorting: false,
    meta: { className: "max-lg:hidden" },
    cell: ({ row }) => <RoleChange event={row.original} />,
  },
  {
    accessorKey: "actor",
    header: t.list.columns.by,
    enableSorting: false,
    meta: { skeleton: "avatar", className: "max-lg:hidden" },
    cell: ({ row }) => <Actor event={row.original} />,
  },
];

/** The value of `when` in words: a preset's name, or the custom days. */
function whenLabel(value: string, t: Messages, language: Language): string {
  if (value in t.list.within) return t.list.within[value as keyof Messages["list"]["within"]];
  const range = parseRange(value);
  return range ? rangeLabel(range, t.list, language) : value;
}

/** The facets; `when` also lists a custom range the URL holds, so its chip names the days. */
const filtersOf = (t: Messages, language: Language, when: string | undefined): TableFilter[] => [
  {
    id: "change",
    title: t.list.columns.change,
    options: CHANGES.map((c) => ({
      value: c,
      label: t.list.changes[c],
      icon: CHANGE_LOOKS[c].icon,
    })),
  },
  {
    id: "when",
    title: t.list.columns.when,
    single: true,
    options: [
      ...WHEN_PRESETS.map((w) => ({ value: w, label: t.list.within[w] })),
      ...(when && parseRange(when)
        ? [{ value: when, label: whenLabel(when, t, language), icon: CalendarRange }]
        : []),
    ],
  },
];

const paramsOf = (t: Messages, everyLibrary: boolean): TableParam[] => [
  ...(everyLibrary ? [{ id: "library", title: t.list.library, mono: true }] : []),
  { id: "actor", title: t.list.actor },
  { id: "subject", title: t.list.subject },
];

interface Props {
  view: AccessLogView;
  config: TableConfig;
  source: ServerSource<AccessEvent>;
  /** The operators' log of every library: a library filter, and each event names its library. */
  everyLibrary?: boolean;
}

/** The access log: who changed access, how and when, newest first unless sorted, a page at a time. */
export function AccessLogTable({ view, config, source, everyLibrary = false }: Props) {
  const id = useId();
  const t = useMessages(messages);
  const language = useLanguage();
  const navigate = useNavigate();
  const columns = useMemo(() => columnsOf(t, everyLibrary), [t, everyLibrary]);
  const filters = useMemo(() => filtersOf(t, language, view.when), [t, language, view.when]);
  const params = useMemo(() => paramsOf(t, everyLibrary), [t, everyLibrary]);
  const model = useDataTable({
    config,
    search: view,
    columns,
    getRowId: (event) => event.id,
    filters,
    params,
    source,
  });

  const actions = (event: AccessEvent): RowAction<AccessEvent>[] => {
    const [, owner = "", repo = ""] = event.library.split("/");
    const { actor, subject } = event;
    return [
      ...(everyLibrary && event.change !== "library_deleted"
        ? [
            {
              id: "open",
              label: t.list.actions.openLibrary,
              icon: ArrowRight,
              motion: "forward" as const,
              onSelect: () =>
                void navigate({ to: "/libraries/$owner/$repo", params: { owner, repo } }),
            },
          ]
        : []),
      ...(everyLibrary
        ? [
            {
              id: "library-entries",
              label: t.list.actions.libraryEntries,
              icon: ListFilter,
              motion: "tilt" as const,
              onSelect: () => model.setParam("library", event.library),
            },
          ]
        : []),
      // The log names a person as it shows them (a username, or the ID of a removed account),
      // which is what the filters take. Changes the instance made name nobody.
      ...(actor
        ? [
            {
              id: "actor-entries",
              label: t.list.actions.actorEntries,
              icon: UserRound,
              motion: "tilt" as const,
              onSelect: () => model.setParam("actor", actor),
            },
          ]
        : []),
      ...(subject && event.change !== "library_deleted"
        ? [
            {
              id: "subject-entries",
              label:
                event.kind === "group"
                  ? t.list.actions.groupEntries
                  : t.list.actions.subjectEntries,
              icon: event.kind === "group" ? Users : UserRound,
              motion: "tilt" as const,
              onSelect: () => model.setParam("subject", subject),
            },
          ]
        : []),
    ];
  };

  return (
    <>
      <DataTableToolbar model={model}>
        <CustomDates model={model} />
        {everyLibrary && (
          <LibraryCombobox
            label={t.list.library}
            hint={t.list.libraryHint}
            query={filterLibrariesQueryOptions}
            custom={isLibraryId}
            value={model.param("library")}
            onChange={(library) => model.setParam("library", library)}
            className="flex-1 basis-60"
          />
        )}
        <SearchFilter
          id={`${id}-actor`}
          label={t.list.actor}
          placeholder={t.list.actorPlaceholder}
          value={model.param("actor")}
          onCommit={(actor) => model.setParam("actor", actor)}
        />
        <SearchFilter
          id={`${id}-subject`}
          label={t.list.subject}
          placeholder={t.list.subjectPlaceholder}
          value={model.param("subject")}
          onCommit={(subject) => model.setParam("subject", subject)}
        />
      </DataTableToolbar>
      <DataTable
        model={model}
        label={t.list.label}
        rowActions={actions}
        rowLabel={(event) => t.list.row(sentenceOf(event, language), event.library)}
        empty={{ icon: ScrollText, title: t.list.emptyTitle, body: t.list.emptyBody }}
        noMatch={{ title: t.list.noMatchTitle, body: t.list.noMatch }}
        errorMessage={
          model.error ? explainAccessLogError(model.error, language) : t.list.loadFailed
        }
      />
      <DataTablePagination model={model} />
    </>
  );
}
