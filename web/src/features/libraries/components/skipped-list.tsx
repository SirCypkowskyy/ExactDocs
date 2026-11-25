import { CircleSlash, Copy, FileWarning, Info } from "lucide-react";
import { useMemo } from "react";
import { toast } from "sonner";
import { useMessages } from "@/shared/lib/i18n";
import { Badge } from "@/shared/ui/badge";
import { StateBadge } from "@/shared/ui/data-table/cells";
import { DataTable } from "@/shared/ui/data-table/data-table";
import type { ColumnDef } from "@/shared/ui/data-table/features";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import type { RowAction } from "@/shared/ui/data-table/row-actions";
import type { TableConfig } from "@/shared/ui/data-table/table-search";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import { type TableFilter, useLocalDataTable } from "@/shared/ui/data-table/use-data-table";

import { progressMessages } from "../messages/progress";
import { type ProblemSummary, skippedLabel } from "../model/add-library";

/*
 * The files a finished job left out or kept with a note (blocks-map §2.3, "Job problems"): one
 * client table of up to 1,000 skips and 200 notes, sorted, filtered and paged in the browser. Its
 * view stays in the component: the page around it owns the URL.
 */

type Messages = (typeof progressMessages)["en"]["skipped"];

const RESULTS = ["skipped", "noted"] as const;

interface ProblemRow {
  path: string;
  code: string;
  reason: string;
  result: (typeof RESULTS)[number];
}

const PROBLEMS_TABLE: TableConfig = {
  id: "job-problems",
  sortFields: ["path", "code"],
  maxRows: 1200,
};

const rowsOf = (summary: ProblemSummary): ProblemRow[] => [
  ...summary.skipGroups.flatMap((g) =>
    g.files.map((f) => ({
      path: f.path,
      code: f.code,
      reason: f.reason,
      result: "skipped" as const,
    })),
  ),
  ...summary.notes.map((n) => ({
    path: n.path,
    code: n.code,
    reason: n.reason,
    result: "noted" as const,
  })),
];

const columnsOf = (t: Messages): ColumnDef<ProblemRow>[] => [
  {
    accessorKey: "path",
    header: t.columns.path,
    enableHiding: false,
    meta: { priority: 1, skeleton: "mono" },
    cell: ({ row }) => (
      <span className="font-mono text-mono [overflow-wrap:anywhere]">{row.original.path}</span>
    ),
  },
  {
    accessorKey: "code",
    header: t.columns.problem,
    meta: { priority: 2, skeleton: "pill" },
    cell: ({ row }) => (
      <span className="flex min-w-0 flex-col items-start gap-1">
        <Badge className="font-mono">{row.original.code}</Badge>
        <span className="text-muted-foreground [overflow-wrap:anywhere]">
          {row.original.reason}
        </span>
      </span>
    ),
  },
  {
    accessorKey: "result",
    header: t.columns.result,
    enableSorting: false,
    meta: { priority: 3, skeleton: "pill" },
    cell: ({ row }) =>
      row.original.result === "skipped" ? (
        <StateBadge state="skipped" label={t.results.skipped} />
      ) : (
        <Badge>
          <Info aria-hidden="true" className="size-3" />
          {t.notes}
        </Badge>
      ),
  },
];

/** The files an import left out, and the files it kept with a note, in one table. */
export function SkippedList({ summary }: { summary: ProblemSummary }) {
  const t = useMessages(progressMessages).skipped;
  const { skipped, notes, truncated } = summary;
  const rows = useMemo(() => rowsOf(summary), [summary]);
  const columns = useMemo(() => columnsOf(t), [t]);
  const filters = useMemo<TableFilter[]>(
    () => [
      {
        id: "code",
        title: t.columns.problem,
        options: [
          ...summary.skipGroups.map((g) => ({ value: g.code, label: g.known ? g.label : g.code })),
          ...[...new Set(summary.notes.map((n) => n.code))].map((code) => ({
            value: code,
            label: code,
          })),
        ],
      },
      {
        id: "result",
        title: t.columns.result,
        options: [
          { value: "skipped", label: t.results.skipped, icon: CircleSlash },
          { value: "noted", label: t.notes, icon: Info },
        ],
      },
    ],
    [summary, t],
  );
  const model = useLocalDataTable({
    config: PROBLEMS_TABLE,
    rows,
    columns,
    getRowId: (row) => `${row.result}:${row.code}:${row.path}`,
    filters,
  });
  if (skipped === 0 && notes.length === 0 && !truncated) return null;
  const actions = (row: ProblemRow): RowAction<ProblemRow>[] => [
    {
      id: "copy",
      label: t.copyPath,
      icon: Copy,
      motion: "pop",
      onSelect: () => {
        void navigator.clipboard?.writeText(row.path).then(
          () => toast.success(t.pathCopied),
          () => {},
        );
      },
    },
  ];
  const leftOut = skipped > 0 || truncated;
  return (
    <section aria-labelledby="skipped-title" className="fade-in mt-8">
      <h3 id="skipped-title" className="flex items-center gap-2 text-section font-semibold">
        <FileWarning aria-hidden="true" className="size-4 text-muted-foreground" />
        <span>
          {leftOut ? t.title : t.notes}{" "}
          <span className="font-normal text-muted-foreground tabular-nums">
            ({leftOut ? skippedLabel(summary) : notes.length})
          </span>
        </span>
      </h3>
      {leftOut && <p className="mt-1 text-body text-muted-foreground">{t.leftOut}</p>}
      <div className="mt-4">
        <DataTableToolbar
          model={model}
          search={{ label: t.find, placeholder: t.findPlaceholder }}
          columns={false}
        />
        <DataTable
          model={model}
          label={leftOut ? t.title : t.notes}
          rowActions={actions}
          rowLabel={(row) => row.path}
          noMatch={{ title: t.noMatch }}
        />
        <DataTablePagination model={model} />
      </div>
      {truncated && <p className="mt-4 text-body text-muted-foreground">{t.firstOnly(skipped)}</p>}
    </section>
  );
}
