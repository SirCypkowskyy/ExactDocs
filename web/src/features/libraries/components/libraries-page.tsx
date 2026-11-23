import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  ArrowRight,
  Copy,
  ExternalLink,
  LibraryBig,
  ListFilter,
  RefreshCw,
  Settings,
  Share2,
} from "lucide-react";
import { useMemo } from "react";
import { toast } from "sonner";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { useNow } from "@/shared/lib/use-now";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Button } from "@/shared/ui/button";
import { DataTable } from "@/shared/ui/data-table/data-table";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import type { RowAction } from "@/shared/ui/data-table/row-actions";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import { useDataTable } from "@/shared/ui/data-table/use-data-table";
import { Page, PageHeader } from "@/shared/ui/page";
import { librariesKeys, librariesSource } from "../api/libraries-query";
import { syncLibrary } from "../api/sync-library";
import { SyncContext } from "../hooks/sync-context";
import { useSyncStates } from "../hooks/use-libraries";
import { listMessages } from "../messages/list";
import { explainSync, type Library, syncOutcome } from "../model/library";
import { LIBRARIES_TABLE, parseListView } from "../model/list-view";
import { AddLibraryLink } from "./add-library-link";
import { FirstRun, PhoneSort } from "./libraries-list";
import { columnsOf, filtersOf } from "./library-columns";

/*
 * Every library the caller may read (blocks-map §2.3, "Libraries"): numbered pages sorted and
 * filtered by the server, the view in the URL, each library's sync from one polled request, and
 * row actions in a kebab and a context menu.
 */

/** Syncing a library now: a toast says what happened, since the row only changes on the next poll. */
function useSyncNow() {
  const t = useMessages(listMessages).actions;
  const language = useLanguage();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (library: Library) => syncLibrary(library.id),
    onSuccess: (result, library) => {
      const outcome = syncOutcome(result);
      if (outcome === "failed") toast.error(t.syncFailed(library.id));
      else toast.success(outcome === "queued" ? t.syncQueued(library.id) : t.upToDate(library.id));
    },
    onError: (error) => toast.error(explainSync(error, language)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: librariesKeys.latestJobs() }),
  });
}

export function LibrariesPage() {
  const view = parseListView(useSearch({ strict: false }) as Record<string, unknown>);
  const t = useMessages(listMessages);
  const heading = usePageTitle(t.title);
  const navigate = useNavigate();
  const now = useNow();
  const syncs = useSyncStates();
  const syncNow = useSyncNow();
  const columns = useMemo(() => columnsOf(t), [t]);
  const filters = useMemo(() => filtersOf(t), [t]);
  const model = useDataTable({
    config: LIBRARIES_TABLE,
    search: view,
    columns,
    getRowId: (library) => library.id,
    filters,
    source: librariesSource(view, now),
  });

  const actions = (library: Library): RowAction<Library>[] => {
    const [, owner = "", repo = ""] = library.id.split("/");
    const params = { owner, repo };
    return [
      {
        id: "open",
        label: t.actions.open,
        icon: ArrowRight,
        motion: "forward",
        onSelect: () => void navigate({ to: "/libraries/$owner/$repo", params }),
      },
      {
        id: "settings",
        label: t.actions.settings,
        icon: Settings,
        motion: "cog",
        onSelect: () => void navigate({ to: "/libraries/$owner/$repo/settings", params }),
      },
      {
        id: "sharing",
        label: t.actions.sharing,
        icon: Share2,
        motion: "out",
        onSelect: () => void navigate({ to: "/libraries/$owner/$repo/sharing", params }),
      },
      {
        id: "sync",
        label: t.actions.syncNow,
        icon: RefreshCw,
        motion: "refresh",
        group: true,
        onSelect: () => {
          if (!syncNow.isPending) syncNow.mutate(library);
        },
      },
      {
        id: "jobs",
        label: t.actions.jobs,
        icon: ListFilter,
        motion: "tilt",
        onSelect: () => void navigate({ to: "/jobs", search: { library: library.id } }),
      },
      {
        id: "copy-id",
        label: t.actions.copyId,
        icon: Copy,
        motion: "pop",
        group: true,
        onSelect: () => {
          void navigator.clipboard?.writeText(library.id).then(
            () => toast.success(t.actions.copied),
            () => {},
          );
        },
      },
      {
        id: "repository",
        label: t.actions.repository,
        icon: ExternalLink,
        motion: "out",
        onSelect: () => void window.open(library.source_url, "_blank", "noopener,noreferrer"),
      },
    ];
  };

  const firstRun = model.status === "ready" && model.total === 0 && !model.filtered;
  return (
    <Page>
      <PageHeader
        title={t.title}
        icon={<LibraryBig />}
        headingRef={heading}
        actions={!firstRun && model.status === "ready" && <AddLibraryLink />}
        description={
          model.total !== undefined &&
          !firstRun && (
            <>
              {/* Atomic: one sentence is announced, and the sync counts only once they are known. */}
              <p role="status" aria-atomic="true" className="num">
                {t.count(model.total)}
                {!syncs.loading && syncs.failed > 0 && (
                  <>
                    {" · "}
                    <span className="font-medium text-destructive">
                      {t.syncsFailed(syncs.failed)}
                    </span>
                  </>
                )}
                {!syncs.loading && syncs.running > 0 && ` · ${t.importing(syncs.running)}`}
              </p>
              {syncs.failedToLoad && (
                <p className="mt-1 flex flex-wrap items-center gap-x-2">
                  {t.syncLoadFailed}
                  <Button variant="ghost" size="sm" className="-ml-1" onClick={syncs.retry}>
                    <RefreshCw aria-hidden="true" data-icon-motion="refresh" />
                    {t.retry}
                  </Button>
                </p>
              )}
            </>
          )
        }
      />
      {firstRun ? (
        <FirstRun />
      ) : (
        <SyncContext value={syncs}>
          <DataTableToolbar
            model={model}
            search={{ label: t.toolbar.find, placeholder: t.toolbar.findPlaceholder }}
          >
            <PhoneSort view={view} />
          </DataTableToolbar>
          <DataTable
            model={model}
            label={t.title}
            rowActions={actions}
            rowLabel={(library) => library.id}
            empty={{ icon: LibraryBig, title: t.firstRun.title, action: <AddLibraryLink /> }}
            noMatch={{ title: t.noMatch.title, body: t.noMatch.body }}
            errorMessage={t.loadFailed}
          />
          <DataTablePagination model={model} />
        </SyncContext>
      )}
    </Page>
  );
}
