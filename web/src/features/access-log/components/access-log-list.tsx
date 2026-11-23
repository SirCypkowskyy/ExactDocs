import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import {
  ArrowRight,
  ArrowRightLeft,
  ListFilter,
  type LucideIcon,
  Plus,
  ScrollText,
  Trash2,
  UserCheck,
  UserMinus,
  UserPen,
  Users,
} from "lucide-react";
import { useId, useMemo, useState } from "react";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Badge, type BadgeTone } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { LibraryCell, Person, RelativeTime } from "@/shared/ui/data-table/cells";
import { DataTable } from "@/shared/ui/data-table/data-table";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import type { RowAction } from "@/shared/ui/data-table/row-actions";
import { pageQueryOptions, type ServerSource } from "@/shared/ui/data-table/server-pages";
import { pageOf, type TableConfig } from "@/shared/ui/data-table/table-search";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import {
  type DataTableModel,
  type TableFilter,
  type TableParam,
  useDataTable,
} from "@/shared/ui/data-table/use-data-table";
import { Input } from "@/shared/ui/input";
import { messages } from "../messages";
import {
  type AccessEvent,
  type AccessLogView,
  CHANGES,
  type Change,
  describeEvent,
  explainAccessLogError,
  isLibraryId,
} from "../model/access-log";

/*
 * The access log as a table (blocks-map §2.3, "Access log"): who changed access, how and when,
 * newest first, numbered pages over the cursor API, the change filter (and, for operators, the
 * library) in the URL. On a phone each row is a card titled by the event's sentence.
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
// remount it. Nothing sorts: the API lists newest first only.
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
    enableSorting: false,
    enableHiding: false,
    meta: { priority: 2 },
    cell: ({ row }) => <RelativeTime iso={row.original.at} />,
  },
  ...(everyLibrary
    ? [
        {
          accessorKey: "library",
          header: t.list.columns.library,
          enableSorting: false,
          meta: { priority: 3, skeleton: "avatar" },
          cell: ({ row }) => <LibraryCell id={row.original.library} />,
        } satisfies ColumnDef<AccessEvent>,
      ]
    : []),
  {
    accessorKey: "change",
    header: t.list.columns.change,
    enableSorting: false,
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

const filtersOf = (t: Messages): TableFilter[] => [
  {
    id: "change",
    title: t.list.columns.change,
    options: CHANGES.map((c) => ({
      value: c,
      label: t.list.changes[c],
      icon: CHANGE_LOOKS[c].icon,
    })),
  },
];

const paramsOf = (t: Messages): TableParam[] => [
  { id: "library", title: t.list.library, mono: true },
];

/** The operators' library filter: a typed `/owner/repo`, checked before it reaches the URL. */
function LibraryFilter<T>({ model }: { model: DataTableModel<T> }) {
  const id = useId();
  const t = useMessages(messages).list;
  const current = model.param("library");
  const [library, setLibrary] = useState(current ?? "");
  const [shown, setShown] = useState(current);
  // A removed chip (or a row's action) changes the filter from outside: the field follows it.
  if (shown !== current) {
    setShown(current);
    setLibrary(current ?? "");
  }
  const invalid = library.trim() !== "" && !isLibraryId(library);
  return (
    <form
      className="flex min-w-0 flex-1 basis-60 flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!invalid) model.setParam("library", library.trim() || undefined);
      }}
    >
      <label htmlFor={`${id}-library`} className="text-body font-medium">
        {t.library}
      </label>
      <div className="flex gap-2">
        <Input
          id={`${id}-library`}
          type="search"
          value={library}
          aria-invalid={invalid || undefined}
          aria-describedby={`${id}-library-hint`}
          onChange={(e) => {
            setLibrary(e.target.value);
            if (!e.target.value.trim() && current) model.setParam("library", undefined);
          }}
          placeholder="/owner/repo"
          className="font-mono"
        />
        <Button type="submit" variant="outline">
          <ListFilter aria-hidden="true" data-icon-motion="tilt" />
          {t.filter}
        </Button>
      </div>
      <p id={`${id}-library-hint`} className="text-small text-muted-foreground">
        {invalid ? t.libraryInvalid : t.libraryHint}
      </p>
    </form>
  );
}

/** Why the shown page failed, in one sentence (the table's own query, read from the cache). */
function useLoadError(source: ServerSource<AccessEvent>, view: AccessLogView, config: TableConfig) {
  const client = useQueryClient();
  const language = useLanguage();
  const { page, size } = pageOf(view, config);
  const error = client.getQueryState(pageQueryOptions(source, page, size).queryKey)?.error;
  return error ? explainAccessLogError(error, language) : undefined;
}

interface Props {
  view: AccessLogView;
  config: TableConfig;
  source: ServerSource<AccessEvent>;
  /** The operators' log of every library: a library filter, and each event names its library. */
  everyLibrary?: boolean;
}

/** The access log: who changed access, how and when, newest first, a page at a time. */
export function AccessLogTable({ view, config, source, everyLibrary = false }: Props) {
  const t = useMessages(messages);
  const language = useLanguage();
  const navigate = useNavigate();
  const columns = useMemo(() => columnsOf(t, everyLibrary), [t, everyLibrary]);
  const filters = useMemo(() => filtersOf(t), [t]);
  const params = useMemo(() => (everyLibrary ? paramsOf(t) : []), [t, everyLibrary]);
  const model = useDataTable({
    config,
    search: view,
    columns,
    getRowId: (event) => event.id,
    filters,
    params,
    source,
  });
  const loadError = useLoadError(source, view, config);

  const actions = (event: AccessEvent): RowAction<AccessEvent>[] => {
    if (!everyLibrary) return [];
    const [, owner = "", repo = ""] = event.library.split("/");
    return [
      ...(event.change === "library_deleted"
        ? []
        : [
            {
              id: "open",
              label: t.list.actions.openLibrary,
              icon: ArrowRight,
              motion: "forward" as const,
              onSelect: () =>
                void navigate({ to: "/libraries/$owner/$repo", params: { owner, repo } }),
            },
          ]),
      {
        id: "library-entries",
        label: t.list.actions.libraryEntries,
        icon: ListFilter,
        motion: "tilt",
        onSelect: () => model.setParam("library", event.library),
      },
    ];
  };

  return (
    <>
      <DataTableToolbar model={model}>
        {everyLibrary && <LibraryFilter model={model} />}
      </DataTableToolbar>
      <DataTable
        model={model}
        label={t.list.label}
        rowActions={actions}
        rowLabel={(event) => t.list.row(sentenceOf(event, language), event.library)}
        empty={{ icon: ScrollText, title: t.list.emptyTitle, body: t.list.emptyBody }}
        noMatch={{ title: t.list.noMatchTitle, body: t.list.noMatch }}
        errorMessage={loadError ?? t.list.loadFailed}
      />
      <DataTablePagination model={model} />
    </>
  );
}
