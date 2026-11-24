import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { CircleAlert, ListOrdered, RefreshCw, Trophy, UsersRound } from "lucide-react";
import { useMemo } from "react";
import { HttpError } from "@/shared/lib/http";
import { common, type Language, useLanguage, useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { Count, LibraryCell, Person } from "@/shared/ui/data-table/cells";
import { DataTable } from "@/shared/ui/data-table/data-table";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import { useDataTable } from "@/shared/ui/data-table/use-data-table";
import { Meter } from "@/shared/ui/meter";
import { EmptyState, Page, PageHeader, Section } from "@/shared/ui/page";
import { ToggleGroup, ToggleGroupItem } from "@/shared/ui/toggle-group";
import { leaderboardQueryOptions, statsSettingsQueryOptions } from "../api/leaderboard";
import { leaderboardMessages } from "../messages";
import {
  type Board,
  boardOf,
  DEFAULTS,
  type Entry,
  keyOf,
  LEADERBOARD_TABLE,
  type Leaderboard,
  type LeaderboardView,
  METRICS,
  type Metric,
  movementOf,
  nameOf,
  PERIODS,
  parseLeaderboardView,
  SUBJECTS,
  type Subject,
  shareOf,
  TOP,
} from "../model/leaderboard";
import { MovementMark } from "./movement";
import { Podium, PodiumSkeleton } from "./podium";

/*
 * Tools → Leaderboard (blocks-map §5.3, #510): the top ten as columns, ranks 11 and up in a
 * client DataTable. Subject, metric and period are segmented controls whose choice lives in the
 * URL with the table's view. The people board shows only while the operator turned it on, and
 * only people who opted in (Account → Interface); the libraries board is always there.
 */

type M = (typeof leaderboardMessages)["en"];

const dateFormats = new Map<Language, Intl.DateTimeFormat>();
/** "Nov 23, 2026" / "23 lis 2026": a UTC day. */
function formatDate(day: string, language: Language): string {
  let format = dateFormats.get(language);
  if (!format) {
    format = new Intl.DateTimeFormat(language, { dateStyle: "medium", timeZone: "UTC" });
    dateFormats.set(language, format);
  }
  return format.format(new Date(`${day}T00:00:00Z`));
}

/** One segmented control whose value lives in the URL (the default is left out). */
function Choice<T extends string>({
  label,
  value,
  options,
  names,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly T[];
  names: Readonly<Record<T, string>>;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span aria-hidden="true" className="text-small text-muted-foreground">
        {label}
      </span>
      <ToggleGroup
        type="single"
        aria-label={label}
        value={value}
        onValueChange={(next) => {
          if (next) onChange(next as T);
        }}
        className="flex-wrap"
      >
        {options.map((o) => (
          <ToggleGroupItem key={o} value={o}>
            {names[o]}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}

function InterfaceLink({ t }: { t: M }) {
  return (
    <Link
      to="/account"
      search={{ tab: "interface" }}
      className="font-medium text-foreground underline underline-offset-4 outline-none focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring"
    >
      {t.people.interfaceLink}
    </Link>
  );
}

/** A short note under the controls: how the people board works, and how to be on it. */
function PeopleNote({
  t,
  tone,
  title,
  body,
}: {
  t: M;
  tone: "muted" | "notice";
  title: string;
  body: string;
}) {
  return (
    <div
      role="note"
      className={
        tone === "notice"
          ? "flex items-start gap-3 rounded-lg bg-route-soft px-4 py-3"
          : "flex items-start gap-3 rounded-lg border border-border px-4 py-3"
      }
    >
      <UsersRound aria-hidden="true" className="mt-0.5 size-4 flex-none text-muted-foreground" />
      <p className="text-body">
        <span className="font-medium">{title}</span>{" "}
        <span className="text-muted-foreground">
          {body} <InterfaceLink t={t} />.
        </span>
      </p>
    </div>
  );
}

const columnsOf = (t: M, subject: Subject, metric: Metric, total: number): ColumnDef<Entry>[] => [
  {
    id: "rank",
    accessorKey: "rank",
    header: t.columns.rank,
    enableGlobalFilter: false,
    meta: { priority: 2, skeleton: "number", label: t.columns.rank },
    cell: ({ row }) => <span className="num font-semibold">#{row.original.rank}</span>,
  },
  {
    id: "name",
    accessorFn: nameOf,
    header: subject === "libraries" ? t.columns.library : t.columns.person,
    enableHiding: false,
    meta: { priority: 1, skeleton: "avatar" },
    cell: ({ row }) => {
      const e = row.original;
      return subject === "libraries" ? (
        <LibraryCell id={nameOf(e)} />
      ) : (
        <Person name={nameOf(e)}>
          {e.you && (
            <Badge tone="route" className="ml-1">
              {t.you}
            </Badge>
          )}
        </Person>
      );
    },
  },
  {
    id: "value",
    accessorKey: "value",
    header: t.metrics[metric],
    sortDescFirst: true,
    enableGlobalFilter: false,
    meta: { priority: 2, align: "end", skeleton: "number" },
    cell: ({ row }) => <Count value={row.original.value} />,
  },
  {
    id: "share",
    accessorFn: (e) => shareOf(e.value, total),
    header: t.columns.share,
    enableSorting: false,
    enableGlobalFilter: false,
    meta: { priority: 3, skeleton: "meter", className: "max-md:hidden", label: t.columns.share },
    cell: ({ row }) => {
      const share = shareOf(row.original.value, total);
      return (
        <span className="flex min-w-32 items-center gap-2">
          <Meter
            role="meter"
            value={share}
            label={t.shareOf(nameOf(row.original))}
            className="max-w-32"
          />
          <span className="num text-small text-muted-foreground">{share}%</span>
        </span>
      );
    },
  },
  {
    id: "change",
    accessorFn: (e) => e.previous_rank ?? -1,
    header: t.columns.change,
    enableSorting: false,
    enableGlobalFilter: false,
    meta: { priority: 3, label: t.columns.change },
    cell: ({ row }) => <MovementMark movement={movementOf(row.original)} words />,
  },
];

/** Writes a choice of board to the URL (a default is left out) and goes back to page 1. */
function useChoose() {
  const navigate = useNavigate();
  return (patch: Partial<Board>) =>
    void navigate({
      to: ".",
      search: (prev: Record<string, unknown>) => {
        const next: Record<string, unknown> = { ...prev, page: undefined };
        for (const [key, value] of Object.entries(patch)) {
          next[key] = value === DEFAULTS[key as keyof Board] ? undefined : value;
        }
        return next;
      },
      replace: true,
      resetScroll: false,
    } as never);
}

/** Subject (only while the people board is on), metric and period. */
function BoardControls({ board, peopleOn }: { board: Board; peopleOn: boolean }) {
  const t = useMessages(leaderboardMessages);
  const choose = useChoose();
  return (
    <fieldset className="flex flex-wrap items-end gap-x-6 gap-y-3">
      <legend className="sr-only">{t.controls}</legend>
      {peopleOn && (
        <Choice
          label={t.subject}
          value={board.subject}
          options={SUBJECTS}
          names={t.subjects}
          onChange={(subject) => choose({ subject })}
        />
      )}
      <Choice
        label={t.metric}
        value={board.metric}
        options={METRICS}
        names={t.metrics}
        onChange={(metric) => choose({ metric })}
      />
      <Choice
        label={t.period}
        value={board.period}
        options={PERIODS}
        names={t.periods}
        onChange={(period) => choose({ period })}
      />
    </fieldset>
  );
}

/** The board failed: say so, and offer the way on (the libraries board, or another try). */
function BoardProblem({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const t = useMessages(leaderboardMessages);
  const c = useMessages(common);
  const choose = useChoose();
  const off = error instanceof HttpError && error.code === "people_leaderboard_off";
  return (
    <EmptyState
      role="alert"
      icon={<CircleAlert aria-hidden="true" />}
      title={off ? t.people.gone : t.failed}
      action={
        <Button
          variant="outline"
          size="sm"
          onClick={() => (off ? choose({ subject: "libraries" }) : onRetry())}
        >
          <RefreshCw aria-hidden="true" data-icon-motion="refresh" />
          {off ? t.subjects.libraries : c.retry}
        </Button>
      }
    />
  );
}

/** Ranks 11 and up: a client DataTable whose view (search, sort, page, size) is in the URL. */
function RestTable({
  view,
  board,
  board: { subject, metric },
  shown,
  refetch,
}: {
  view: LeaderboardView;
  board: Board;
  shown: Leaderboard | undefined;
  refetch: () => void;
}) {
  const t = useMessages(leaderboardMessages);
  const rest = useMemo(() => shown?.entries.slice(TOP) ?? [], [shown]);
  const total = shown?.total ?? 0;
  const columns = useMemo(() => columnsOf(t, subject, metric, total), [t, subject, metric, total]);
  const model = useDataTable({
    config: LEADERBOARD_TABLE,
    search: view,
    columns,
    getRowId: keyOf,
    query: { data: rest, isPending: !shown, isError: false, refetch },
  });
  if (shown && rest.length === 0) return null;
  return (
    <Section id="rest" title={t.rest} icon={<ListOrdered />}>
      <DataTableToolbar
        model={model}
        columns={false}
        search={{
          label: t.find,
          placeholder: subject === "libraries" ? t.findLibrary : t.findPerson,
        }}
      />
      <DataTable
        model={model}
        label={t.rest}
        rowLabel={nameOf}
        empty={{ icon: ListOrdered, title: t.empty[board.metric][board.period] }}
        noMatch={{ title: t.noMatch }}
        errorMessage={t.failed}
      />
      <DataTablePagination model={model} />
    </Section>
  );
}

/** The board's dates under the page title: "Week: Nov 23, 2026 – Nov 29, 2026". */
function PeriodLine({ board, shown }: { board: Board; shown: Leaderboard | undefined }) {
  const t = useMessages(leaderboardMessages);
  const language = useLanguage();
  if (!shown) return null;
  return (
    <p role="status" className="mt-1 text-small">
      {t.periods[board.period]}:{" "}
      {t.range(formatDate(shown.start, language), formatDate(shown.end, language))}
    </p>
  );
}

/** How the people board works, and how to be on it: under the controls when it matters. */
function PeopleNotes({
  peopleOn,
  board,
  shown,
}: {
  peopleOn: boolean;
  board: Board;
  shown: Leaderboard | undefined;
}) {
  const t = useMessages(leaderboardMessages);
  if (!peopleOn) {
    return <PeopleNote t={t} tone="muted" title={t.people.off} body={t.people.offBody} />;
  }
  const onBoard = shown?.entries.some((e) => e.you) || Boolean(shown?.you);
  if (board.subject !== "people" || !shown || onBoard) return null;
  return <PeopleNote t={t} tone="notice" title={t.people.notOn} body={t.people.notOnBody} />;
}

/** The top ten: the columns, or the board's skeleton, its failure or "nothing yet". */
function TopTen({
  board,
  shown,
  busy,
  failed,
  error,
  onRetry,
}: {
  board: Board;
  shown: Leaderboard | undefined;
  busy: boolean;
  failed: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  const t = useMessages(leaderboardMessages);
  const body = failed ? (
    <BoardProblem error={error} onRetry={onRetry} />
  ) : !shown ? (
    <PodiumSkeleton />
  ) : shown.entries.length === 0 ? (
    <EmptyState icon={<Trophy aria-hidden="true" />} title={t.empty[board.metric][board.period]}>
      {t.emptyBody}
    </EmptyState>
  ) : (
    <div aria-busy={busy || undefined}>
      <Podium entries={shown.entries} subject={board.subject} metric={board.metric} />
    </div>
  );
  return (
    <Section id="top" title={t.top} icon={<Trophy />}>
      {body}
    </Section>
  );
}

/** Tools → Leaderboard. */
export function LeaderboardPage() {
  const t = useMessages(leaderboardMessages);
  const heading = usePageTitle(t.title);
  const view = parseLeaderboardView(useSearch({ strict: false }) as Record<string, unknown>);
  const settings = useQuery(statsSettingsQueryOptions());
  const peopleOn = settings.data?.people_leaderboard ?? false;
  const board = boardOf(view, peopleOn);
  const query = useQuery({ ...leaderboardQueryOptions(board), enabled: settings.isSuccess });
  // A board of the other subject (kept while the next loads) is never shown under this one.
  const shown = query.data?.subject === board.subject ? query.data : undefined;
  const failed = settings.isError || (query.isError && !shown);
  const retry = () => void (settings.isError ? settings.refetch() : query.refetch());

  return (
    <Page>
      <PageHeader
        title={t.title}
        icon={<Trophy />}
        headingRef={heading}
        description={
          <>
            <p>{t.description}</p>
            <PeriodLine board={board} shown={shown} />
          </>
        }
      />
      <div className="flex flex-col gap-8">
        <BoardControls board={board} peopleOn={peopleOn} />
        {settings.isSuccess && <PeopleNotes peopleOn={peopleOn} board={board} shown={shown} />}
        <TopTen
          board={board}
          shown={shown}
          busy={query.isPlaceholderData}
          failed={failed}
          error={query.error}
          onRetry={retry}
        />
        {!failed && <RestTable view={view} board={board} shown={shown} refetch={retry} />}
        {shown?.you && (
          <p className="num rounded-lg bg-route-soft px-4 py-3 text-body font-medium">
            {t.yourRank(shown.you.rank, t.value[board.metric](shown.you.value))}
          </p>
        )}
      </div>
    </Page>
  );
}
