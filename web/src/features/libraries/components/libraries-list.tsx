import type { ColumnDef } from "@tanstack/react-table";
import { Check, Copy, LibraryBig } from "lucide-react";
import { useEffect, useEffectEvent, useId, useMemo, useState } from "react";
import { toast } from "sonner";
import { common, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { ListFooter, SortHeader, useServerTable } from "@/shared/ui/data-table";
import { Input } from "@/shared/ui/input";
import { EmptyState } from "@/shared/ui/page";
import { codeWell } from "@/shared/ui/recipes";
import { SelectField } from "@/shared/ui/select-field";
import { Skeleton } from "@/shared/ui/skeleton";
import { Tooltip } from "@/shared/ui/tooltip";
import { type SyncState, useNow } from "../hooks/use-libraries";
import { listMessages } from "../messages/list";
import type { Library } from "../model/library";
import { isFiltered, type ListView } from "../model/list-view";
import { AddLibraryLink } from "./add-library-link";
import { LibraryRow, columns as rowColumns } from "./library-row";

interface LibrariesListProps {
  libraries: readonly Library[];
  syncs: ReadonlyMap<string, SyncState>;
  view: ListView;
  onView: (view: ListView) => void;
  total: number;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}

type ListMessages = (typeof listMessages)["en"];

/** Sorting is done by the API, so the table only holds the state and draws the headers. */
const columnDefs = (t: ListMessages["columns"]): ColumnDef<Library>[] => [
  { accessorKey: "title", header: t.library },
  { accessorKey: "version_count", header: t.versions, sortDescFirst: true },
  { accessorKey: "last_imported_at", header: t.lastImported, sortDescFirst: true },
  { id: "sync", header: t.sync, enableSorting: false },
];

const COMMAND = "exactdocs add https://github.com/acme/payments --path docs/";

function FirstRun() {
  const t = useMessages(listMessages).firstRun;
  const c = useMessages(common);
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(COMMAND).then(() => {
      setCopied(true);
      toast.success(t.commandCopied);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <EmptyState
      icon={<LibraryBig aria-hidden="true" />}
      title={t.title}
      action={<AddLibraryLink />}
      className="max-w-2xl"
    >
      <p>{t.intro}</p>
      <p className="mt-4">{t.commandLine}</p>
      <div className="mt-2 flex items-start gap-1">
        <pre className={cn(codeWell, "min-w-0 flex-1 whitespace-pre-wrap")}>
          <code>{COMMAND}</code>
        </pre>
        <Tooltip label={copied ? c.copied : t.copyCommand}>
          <Button variant="ghost" size="icon" onClick={copy} aria-label={t.copyCommand}>
            {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          </Button>
        </Tooltip>
      </div>
    </EmptyState>
  );
}

function Toolbar({
  view,
  onView,
  text,
  setText,
}: Pick<LibrariesListProps, "view" | "onView"> & { text: string; setText: (v: string) => void }) {
  const t = useMessages(listMessages).toolbar;
  const id = useId();
  const commit = useEffectEvent((value: string) => {
    if ((view.q ?? "") !== value.trim()) onView({ ...view, q: value.trim() || undefined });
  });
  // Typing waits a moment before it asks the server.
  useEffect(() => {
    const t = setTimeout(() => commit(text), 300);
    return () => clearTimeout(t);
  }, [text]);
  return (
    <search className="mb-4 flex flex-wrap items-end gap-3">
      <div className="flex min-w-0 flex-1 basis-60 flex-col gap-2">
        <label htmlFor={`${id}-q`} className="text-body font-medium">
          {t.find}
        </label>
        <Input
          id={`${id}-q`}
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t.findPlaceholder}
        />
      </div>
      <div className="w-40">
        <SelectField
          id={`${id}-ai`}
          label={t.ai}
          value={view.ai ?? ""}
          onChange={(e) =>
            onView({
              ...view,
              ai: e.target.value === "" ? undefined : (e.target.value as "on" | "off"),
            })
          }
        >
          <option value="">{t.any}</option>
          <option value="on">{t.aiOn}</option>
          <option value="off">{t.aiOff}</option>
        </SelectField>
      </div>
      <div className="w-48 md:hidden">
        <SelectField
          id={`${id}-sort`}
          label={t.sortBy}
          value={view.sort ?? ""}
          onChange={(e) => onView({ ...view, sort: e.target.value || undefined })}
        >
          <option value="">{t.sortDefault}</option>
          <option value="title">{t.nameAsc}</option>
          <option value="-title">{t.nameDesc}</option>
          <option value="-last_imported_at">{t.recentlyImported}</option>
          <option value="last_imported_at">{t.leastRecentlyImported}</option>
          <option value="-version_count">{t.mostVersions}</option>
          <option value="version_count">{t.fewestVersions}</option>
        </SelectField>
      </div>
    </search>
  );
}

export function LibrariesList({
  libraries,
  syncs,
  view,
  onView,
  total,
  hasMore,
  loadingMore,
  onLoadMore,
}: LibrariesListProps) {
  const t = useMessages(listMessages);
  const now = useNow();
  const [text, setText] = useState(view.q ?? "");
  const columns = useMemo(() => columnDefs(t.columns), [t]);
  const table = useServerTable({
    data: libraries,
    columns,
    getRowId: (library) => library.id,
    sort: view.sort,
    onSort: (sort) => onView({ ...view, sort }),
  });
  if (total === 0 && !isFiltered(view)) return <FirstRun />;
  return (
    <div>
      <Toolbar view={view} onView={onView} text={text} setText={setText} />
      {libraries.length === 0 ? (
        <EmptyState title={t.noMatch.title} className="max-w-2xl">
          <p>{t.noMatch.body}</p>
          <Button
            variant="ghost"
            className="mt-3"
            onClick={() => {
              setText("");
              onView({ sort: view.sort });
            }}
          >
            {t.noMatch.clear}
          </Button>
        </EmptyState>
      ) : (
        <>
          <div
            className={`hidden border-b border-rule pb-2 pl-[3.25rem] text-small text-muted-foreground ${rowColumns}`}
          >
            {table.getHeaderGroups()[0]?.headers.map((header) => (
              <span key={header.id}>
                <SortHeader header={header} />
              </span>
            ))}
          </div>
          <ul aria-label={t.title} className="divide-y divide-rule">
            {table.getRowModel().rows.map(({ original: library }) => (
              <LibraryRow
                key={library.id}
                library={library}
                sync={syncs.get(library.id) ?? { status: "pending" }}
                now={now}
              />
            ))}
            {loadingMore && (
              <li aria-hidden="true" className="py-4">
                <Skeleton className="h-12 w-full" />
              </li>
            )}
          </ul>
          <ListFooter
            shown={libraries.length}
            total={total}
            hasMore={hasMore}
            loadingMore={loadingMore}
            onLoadMore={onLoadMore}
          />
        </>
      )}
    </div>
  );
}
