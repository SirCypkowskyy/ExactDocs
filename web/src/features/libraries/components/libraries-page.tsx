import { useNavigate, useSearch } from "@tanstack/react-router";
import { useCallback, useMemo } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Page, PageHeader } from "@/shared/ui/page";
import { type SyncState, useLibraries, useSyncStates } from "../hooks/use-libraries";
import { listMessages } from "../messages/list";
import { failedFirst } from "../model/library";
import { isFiltered, type ListView, parseListView } from "../model/list-view";
import { AddLibraryLink } from "./add-library-link";
import { LibrariesList } from "./libraries-list";

const kindOf = (s: SyncState | undefined) => (s && "kind" in s ? s.kind : undefined);

export function LibrariesPage() {
  const view = parseListView(useSearch({ strict: false }) as Record<string, unknown>);
  const navigate = useNavigate();
  // The URL holds the view, so a reload or a shared link shows the same list.
  const onView = useCallback(
    (next: ListView) => void navigate({ to: "/", search: { ...next }, replace: true }),
    [navigate],
  );
  const { query, libraries, total, hasMore, loadingMore, loadMore } = useLibraries(view);
  const { syncs, failedToLoad, loading, retry } = useSyncStates(libraries);
  const t = useMessages(listMessages);
  const heading = usePageTitle(t.title);
  // Without a chosen sort, loaded libraries with a failed sync come first.
  const sorted = useMemo(
    () =>
      view.sort ? libraries : failedFirst(libraries, (id) => kindOf(syncs.get(id)) === "failed"),
    [libraries, syncs, view.sort],
  );
  if (query.isError && !query.data) {
    return (
      <Page>
        <PageHeader title={t.title} headingRef={heading} />
        <p role="alert">
          {t.loadFailed}{" "}
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="cursor-pointer font-medium underline"
          >
            {t.retry}
          </button>
        </p>
      </Page>
    );
  }
  const all = [...syncs.values()];
  const failed = all.filter((s) => kindOf(s) === "failed").length;
  const running = all.filter((s) => kindOf(s) === "running").length;
  const showing = total > 0 || isFiltered(view);
  return (
    <Page>
      <PageHeader
        title={t.title}
        headingRef={heading}
        actions={showing && <AddLibraryLink />}
        description={
          showing && (
            <>
              {/* Atomic: one sentence is announced, and the sync counts only once they are known. */}
              <p role="status" aria-atomic="true" className="num">
                {t.count(total)}
                {!loading && failed > 0 && (
                  <>
                    {" · "}
                    <span className="font-medium text-destructive">{t.syncsFailed(failed)}</span>
                  </>
                )}
                {!loading && running > 0 && ` · ${t.importing(running)}`}
              </p>
              {failedToLoad && (
                <p className="mt-1">
                  {t.syncLoadFailed}{" "}
                  <button
                    type="button"
                    onClick={retry}
                    className="min-h-11 cursor-pointer rounded font-medium text-foreground underline underline-offset-2 outline-none hover:text-route focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
                  >
                    {t.retry}
                  </button>
                </p>
              )}
            </>
          )
        }
      />
      <LibrariesList
        libraries={sorted}
        syncs={syncs}
        view={view}
        onView={onView}
        total={total}
        hasMore={hasMore}
        loadingMore={loadingMore}
        onLoadMore={loadMore}
      />
    </Page>
  );
}
