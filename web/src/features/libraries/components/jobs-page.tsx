import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import type { ColumnDef, Table } from "@tanstack/react-table";
import { useCallback, useId } from "react";
import { absoluteTimeWithZone, relativeTime } from "@/shared/lib/time";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { usePrefetchedPages } from "@/shared/lib/use-prefetched-pages";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import {
  ColumnsMenu,
  DataTable,
  ListFooter,
  SearchFilter,
  useServerTable,
} from "@/shared/ui/data-table";
import { EmptyState, Page, PageHeader } from "@/shared/ui/page";
import { SelectField } from "@/shared/ui/select-field";
import { jobsQueryOptions } from "../api/libraries-query";
import { useNow } from "../hooks/use-libraries";
import {
  JOB_KINDS,
  JOB_STATES,
  type JobsView,
  jobsFiltered,
  parseJobsView,
} from "../model/jobs-view";
import type { Job } from "../model/library";

function When({ iso }: { iso: string | null | undefined }) {
  const now = useNow();
  return iso ? (
    <time dateTime={iso} title={absoluteTimeWithZone(iso)}>
      {relativeTime(iso, now)}
    </time>
  ) : (
    <span className="text-muted-foreground">–</span>
  );
}

function LibraryLink({ id }: { id: string }) {
  const [, owner = "", repo = ""] = id.split("/");
  return (
    <Link
      to="/libraries/$owner/$repo"
      params={{ owner, repo }}
      className="rounded font-mono text-mono underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
    >
      {id}
    </Link>
  );
}

// Module level on purpose: a cell is rendered as a component, so a new function would remount it.
const columns: ColumnDef<Job>[] = [
  {
    accessorKey: "library",
    header: "Library",
    enableHiding: false,
    cell: ({ row }) => <LibraryLink id={row.original.library} />,
  },
  {
    accessorKey: "version",
    header: "Version",
    enableSorting: false,
    cell: ({ row }) => <span className="font-mono">{row.original.version ?? "all"}</span>,
  },
  { accessorKey: "kind", header: "Kind", meta: { className: "max-md:hidden" } },
  {
    accessorKey: "state",
    header: "State",
    enableHiding: false,
    cell: ({ row }) => (
      <span
        title={row.original.error ?? undefined}
        className={cn(row.original.state === "failed" && "font-medium text-destructive")}
      >
        {row.original.state}
      </span>
    ),
  },
  {
    accessorKey: "created_at",
    header: "Queued",
    sortDescFirst: true,
    cell: ({ row }) => <When iso={row.original.created_at} />,
  },
  {
    accessorKey: "finished_at",
    header: "Finished",
    enableSorting: false,
    meta: { className: "max-md:hidden" },
    cell: ({ row }) => <When iso={row.original.finished_at} />,
  },
];

function JobsToolbar({
  view,
  onView,
  table,
}: {
  view: JobsView;
  onView: (next: JobsView) => void;
  table: Table<Job>;
}) {
  const id = useId();
  return (
    <search className="mb-4 flex flex-wrap items-end gap-3">
      <SearchFilter
        id={`${id}-q`}
        label="Find a job"
        placeholder="Library, version or error"
        value={view.q}
        onCommit={(q) => onView({ ...view, q })}
      />
      <div className="w-36">
        <SelectField
          id={`${id}-state`}
          label="State"
          value={view.state ?? ""}
          onChange={(e) =>
            onView({ ...view, state: parseJobsView({ state: e.target.value }).state })
          }
        >
          <option value="">Any</option>
          {JOB_STATES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </SelectField>
      </div>
      <div className="w-36">
        <SelectField
          id={`${id}-kind`}
          label="Kind"
          value={view.kind ?? ""}
          onChange={(e) => onView({ ...view, kind: parseJobsView({ kind: e.target.value }).kind })}
        >
          <option value="">Any</option>
          {JOB_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </SelectField>
      </div>
      <ColumnsMenu table={table} />
    </search>
  );
}

function NoJobs({ view, onView }: { view: JobsView; onView: (next: JobsView) => void }) {
  if (!jobsFiltered(view)) {
    return (
      <EmptyState title="No jobs yet">
        <p>Imports and other library work show up here once they are queued.</p>
      </EmptyState>
    );
  }
  return (
    <EmptyState title="No jobs match">
      <p>Nothing matches these filters.</p>
      <Button variant="ghost" className="mt-3" onClick={() => onView({ sort: view.sort })}>
        Clear filters
      </Button>
    </EmptyState>
  );
}

/** Every job the caller may see, sorted and filtered by the server; the view lives in the URL. */
export function JobsPage() {
  const view = parseJobsView(useSearch({ strict: false }) as Record<string, unknown>);
  const navigate = useNavigate();
  const onView = useCallback(
    (next: JobsView) => void navigate({ to: "/jobs", search: { ...next }, replace: true }),
    [navigate],
  );
  const query = useInfiniteQuery(jobsQueryOptions(view));
  const { pages, hasMore, loadingMore, loadMore } = usePrefetchedPages(query, view);
  const jobs = pages.flatMap((p) => p.jobs);
  const total = pages.at(-1)?.total ?? 0;
  const heading = usePageTitle("Jobs");
  const table = useServerTable({
    data: jobs,
    columns,
    getRowId: (job) => job.id,
    sort: view.sort,
    onSort: (sort) => onView({ ...view, sort }),
  });

  return (
    <Page width="wide">
      <PageHeader
        title="Jobs"
        headingRef={heading}
        description={
          query.data && (
            <p role="status" className="num">
              {total} {total === 1 ? "job" : "jobs"}
            </p>
          )
        }
      />
      <JobsToolbar view={view} onView={onView} table={table} />
      {view.library && (
        <p className="mb-3 text-body text-muted-foreground">
          Jobs of <span className="font-mono text-foreground">{view.library}</span>.{" "}
          <button
            type="button"
            onClick={() => onView({ ...view, library: undefined })}
            className="cursor-pointer font-medium text-foreground underline underline-offset-2"
          >
            Show every library
          </button>
        </p>
      )}
      {query.isError && !query.data ? (
        <p role="alert">
          Couldn't load jobs.{" "}
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="cursor-pointer font-medium underline"
          >
            Retry
          </button>
        </p>
      ) : query.data && jobs.length === 0 ? (
        <NoJobs view={view} onView={onView} />
      ) : (
        <>
          <DataTable table={table} label="Jobs" loadingMore={loadingMore || query.isPending} />
          {query.data && (
            <ListFooter
              shown={jobs.length}
              total={total}
              hasMore={hasMore}
              loadingMore={loadingMore}
              onLoadMore={loadMore}
            />
          )}
        </>
      )}
    </Page>
  );
}
