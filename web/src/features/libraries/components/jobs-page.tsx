import { useNavigate, useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { Activity, ArrowRight, Ban, Copy, ListFilter } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { formatDuration } from "@/shared/lib/format";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { useNow } from "@/shared/lib/use-now";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Badge } from "@/shared/ui/badge";
import {
  LibraryCell,
  Person,
  Progress,
  RelativeTime,
  STATE_LOOKS,
  StateBadge,
  VersionCell,
} from "@/shared/ui/data-table/cells";
import { DataTable } from "@/shared/ui/data-table/data-table";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import type { RowAction } from "@/shared/ui/data-table/row-actions";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import {
  type TableFilter,
  type TableParam,
  useDataTable,
} from "@/shared/ui/data-table/use-data-table";
import { LibraryCombobox } from "@/shared/ui/library-combobox";
import { Page, PageHeader } from "@/shared/ui/page";
import { Tooltip } from "@/shared/ui/tooltip";
import { jobsSource, pickerLibrariesQueryOptions } from "../api/libraries-query";
import { jobsMessages } from "../messages/jobs";
import {
  JOB_KINDS,
  JOB_ORIGINS,
  JOB_STATES,
  JOBS_TABLE,
  parseJobsView,
  QUEUED_WITHIN,
} from "../model/jobs-view";
import type { Job } from "../model/library";
import { CancelJobDialog } from "./cancel-job-dialog";

/*
 * Every job the caller may see (blocks-map §2.3, the DataTable v2 pilot): numbered pages sorted
 * and filtered by the server, the view in the URL, row actions in a kebab and a context menu.
 */

type JobsMessages = (typeof jobsMessages)["en"];

/** A state or kind the API sends, by its name; one this client does not know shows as sent. */
const nameOf = (names: Readonly<Record<string, string>>, value: string) => names[value] ?? value;

/** What a job's `done` / `total` count. */
const unitOf = (kind: string) =>
  kind === "embed"
    ? "chunks"
    : kind === "reprocess" || kind === "retag" || kind === "rechunk"
      ? "versions"
      : kind === "collect"
        ? "steps"
        : "files";

const live = (job: Job) => job.state === "queued" || job.state === "running";

function StateCell({ job }: { job: Job }) {
  const t = useMessages(jobsMessages);
  return (
    <span className="flex flex-col items-start gap-1">
      <StateBadge state={job.state} label={nameOf(t.states, job.state)} />
      {job.state === "failed" && job.error_code && (
        <Tooltip label={job.error ?? job.error_code}>
          <span className="font-mono text-small text-muted-foreground">
            {job.error_code}
            {job.error && <span className="sr-only">: {job.error}</span>}
          </span>
        </Tooltip>
      )}
      {job.state === "failed" && !job.error_code && job.error && (
        <span className="max-w-56 truncate text-small text-muted-foreground">{job.error}</span>
      )}
      {job.state === "cancelled" && job.cancelled_by && (
        <span className="text-small text-muted-foreground">{t.cancelledBy(job.cancelled_by)}</span>
      )}
      {job.state === "running" && job.cancelled_at && (
        <span className="text-small text-muted-foreground">{t.stopping}</span>
      )}
    </span>
  );
}

function ProgressCell({ job }: { job: Job }) {
  const t = useMessages(jobsMessages);
  const skipped = job.problems.filter((p) => p.is_skip).length;
  if (job.state === "queued") return <span className="text-muted-foreground">–</span>;
  return (
    <span className="flex flex-col gap-1">
      <Progress
        done={job.done}
        total={job.total}
        unit={unitOf(job.kind)}
        label={t.progressOf(nameOf(t.kinds, job.kind), job.library)}
        meter={job.state === "running"}
      />
      {skipped > 0 && (
        <span className="text-small text-muted-foreground">{t.skipped(skipped)}</span>
      )}
    </span>
  );
}

/** The person whose request queued the job; the instance's own work, or nobody recorded, muted. */
function StartedBy({ job }: { job: Job }) {
  const t = useMessages(jobsMessages);
  if (job.created_by) return <Person name={job.created_by.username} />;
  if (job.origin === "auto") return <span className="text-muted-foreground">{t.automatic}</span>;
  return (
    <Tooltip label={t.notRecordedHint}>
      <span className="text-muted-foreground">
        {t.notRecorded}
        <span className="sr-only">: {t.notRecordedHint}</span>
      </span>
    </Tooltip>
  );
}

function Took({ job }: { job: Job }) {
  const t = useMessages(jobsMessages);
  const language = useLanguage();
  const now = useNow(30_000);
  if (!job.started_at) return <span className="text-muted-foreground">–</span>;
  const start = Date.parse(job.started_at);
  if (job.state === "running") {
    return (
      <span className="whitespace-nowrap text-muted-foreground">
        {t.runningFor(formatDuration(now - start, language))}
      </span>
    );
  }
  if (!job.finished_at) return <span className="text-muted-foreground">–</span>;
  return (
    <span className="num whitespace-nowrap">
      {formatDuration(Date.parse(job.finished_at) - start, language)}
    </span>
  );
}

// Built once per language: a cell is rendered as a component, so a new function would remount it.
const columnsOf = (t: JobsMessages): ColumnDef<Job>[] => [
  {
    accessorKey: "id",
    header: "#",
    sortDescFirst: true,
    meta: { label: t.columns.id, skeleton: "mono", className: "max-lg:hidden" },
    cell: ({ row }) => (
      <span className="font-mono text-mono text-muted-foreground">
        {/* The end of the ID: its start is a timestamp, the same for jobs queued together. */}
        {row.original.id.slice(-8)}
      </span>
    ),
  },
  {
    accessorKey: "library",
    header: t.columns.library,
    enableHiding: false,
    meta: { priority: 1, skeleton: "avatar" },
    cell: ({ row }) => <LibraryCell id={row.original.library} />,
  },
  {
    accessorKey: "version",
    header: t.columns.version,
    enableSorting: false,
    meta: { priority: 2, skeleton: "mono" },
    cell: ({ row }) => (
      <VersionCell
        version={row.original.version}
        sha={row.original.commit_sha}
        empty={t.allVersions}
      />
    ),
  },
  {
    accessorKey: "kind",
    header: t.columns.kind,
    meta: { priority: 3, skeleton: "pill" },
    cell: ({ row }) => <Badge>{nameOf(t.kinds, row.original.kind)}</Badge>,
  },
  {
    accessorKey: "state",
    header: t.columns.state,
    enableHiding: false,
    meta: { priority: 2, skeleton: "pill" },
    cell: ({ row }) => <StateCell job={row.original} />,
  },
  {
    id: "progress",
    header: t.columns.progress,
    enableSorting: false,
    meta: { skeleton: "meter", className: "max-md:hidden" },
    cell: ({ row }) => <ProgressCell job={row.original} />,
  },
  {
    accessorKey: "origin",
    header: t.columns.origin,
    enableSorting: false,
    meta: { className: "max-xl:hidden" },
    cell: ({ row }) => (
      <span className="text-muted-foreground">{nameOf(t.origins, row.original.origin)}</span>
    ),
  },
  {
    id: "created_by",
    header: t.columns.startedBy,
    enableSorting: false,
    meta: { skeleton: "avatar", className: "max-lg:hidden" },
    cell: ({ row }) => <StartedBy job={row.original} />,
  },
  {
    accessorKey: "created_at",
    header: t.columns.queued,
    sortDescFirst: true,
    meta: { priority: 3 },
    cell: ({ row }) => <RelativeTime iso={row.original.created_at} />,
  },
  {
    id: "took",
    header: t.columns.took,
    enableSorting: false,
    meta: { className: "max-md:hidden" },
    cell: ({ row }) => <Took job={row.original} />,
  },
];

const filtersOf = (t: JobsMessages): TableFilter[] => [
  {
    id: "state",
    title: t.state,
    options: JOB_STATES.map((s) => ({
      value: s,
      label: t.states[s],
      ...(STATE_LOOKS[s] && { icon: STATE_LOOKS[s].icon }),
    })),
  },
  {
    id: "kind",
    title: t.kind,
    options: JOB_KINDS.map((k) => ({ value: k, label: t.kinds[k] })),
  },
  {
    id: "origin",
    title: t.columns.origin,
    options: JOB_ORIGINS.map((o) => ({ value: o, label: nameOf(t.origins, o) })),
  },
  {
    id: "created",
    title: t.columns.queued,
    single: true,
    options: QUEUED_WITHIN.map((w) => ({ value: w, label: t.within[w] })),
  },
];

const paramsOf = (t: JobsMessages): TableParam[] => [
  { id: "library", title: t.columns.library, mono: true },
  { id: "version", title: t.columns.version, mono: true },
];

export function JobsPage() {
  const view = parseJobsView(useSearch({ strict: false }) as Record<string, unknown>);
  const t = useMessages(jobsMessages);
  const heading = usePageTitle(t.title);
  const navigate = useNavigate();
  const now = useNow();
  const columns = useMemo(() => columnsOf(t), [t]);
  const filters = useMemo(() => filtersOf(t), [t]);
  const params = useMemo(() => paramsOf(t), [t]);
  const model = useDataTable({
    config: JOBS_TABLE,
    search: view,
    columns,
    getRowId: (job) => job.id,
    filters,
    params,
    source: jobsSource(view, now),
  });
  const [cancelling, setCancelling] = useState<Job>();

  const actions = (job: Job): RowAction<Job>[] => {
    const [, owner = "", repo = ""] = job.library.split("/");
    return [
      {
        id: "open",
        label: t.actions.open,
        icon: ArrowRight,
        motion: "forward",
        onSelect: () => void navigate({ to: "/libraries/$owner/$repo", params: { owner, repo } }),
      },
      {
        id: "library-jobs",
        label: t.actions.libraryJobs,
        icon: ListFilter,
        motion: "tilt",
        onSelect: () => model.setParam("library", job.library),
      },
      {
        id: "copy-id",
        label: t.actions.copyId,
        icon: Copy,
        motion: "pop",
        onSelect: () => {
          void navigator.clipboard?.writeText(job.id).then(
            () => toast.success(t.actions.copied),
            () => {},
          );
        },
      },
      ...(job.cancellable && live(job) && !job.cancelled_at
        ? [
            {
              id: "cancel",
              label: t.actions.cancel,
              icon: Ban,
              motion: "warn" as const,
              destructive: true,
              group: true,
              onSelect: () => setCancelling(job),
            },
          ]
        : []),
    ];
  };

  return (
    <Page width="wide">
      <PageHeader
        title={t.title}
        icon={<Activity />}
        headingRef={heading}
        description={
          model.total !== undefined && (
            <p role="status" className="num">
              {t.count(model.total)}
            </p>
          )
        }
      />
      <DataTableToolbar model={model} search={{ label: t.find, placeholder: t.findPlaceholder }}>
        <LibraryCombobox
          variant="filter"
          label={t.columns.library}
          query={pickerLibrariesQueryOptions}
          value={model.param("library")}
          onChange={(library) => model.setParam("library", library)}
        />
      </DataTableToolbar>
      <DataTable
        model={model}
        label={t.title}
        rowActions={actions}
        rowLabel={(job) =>
          t.row(job.library, job.version ?? t.allVersions, nameOf(t.kinds, job.kind))
        }
        empty={{ icon: Activity, title: t.empty.title, body: t.empty.body }}
        noMatch={{ title: t.noMatch.title, body: t.noMatch.body }}
        errorMessage={t.loadFailed}
      />
      <DataTablePagination model={model} />
      <CancelJobDialog job={cancelling} onClose={() => setCancelling(undefined)} />
    </Page>
  );
}
