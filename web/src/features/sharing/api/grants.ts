import { queryOptions } from "@tanstack/react-query";
import { getJson, sendJson } from "@/shared/lib/http";
import { pageQueryOptions, type ServerSource } from "@/shared/ui/data-table/server-pages";
import { pageOf } from "@/shared/ui/data-table/table-search";
import type { Grant, GrantList, GrantRequest, GrantsNow, SubjectKind } from "../model/grant";
import { GRANTS_TABLE, grantsFilters, grantsParams, type SharingView } from "../model/grants-view";

const seg = encodeURIComponent;
const lib = (owner: string, repo: string) => `/v1/libraries/${seg(owner)}/${seg(repo)}` as const;

/** The root of one library's sharing queries: every change invalidates it. */
export const sharingKey = (owner: string, repo: string) => ["sharing", owner, repo] as const;

/**
 * Who the caller is on the library, who created it and how many grants it has, whatever the
 * table's filters: one unfiltered grant is enough to learn them. A 403 (not an admin of the
 * library) or a 404 will not change by asking again.
 */
export const sharingSummaryQueryOptions = (owner: string, repo: string) =>
  queryOptions({
    queryKey: [...sharingKey(owner, repo), "summary"] as const,
    queryFn: ({ signal }) => getJson<GrantList>(`${lib(owner, repo)}/grants?limit=1`, { signal }),
    retry: false,
  });

/** The grants a view asks for, sorted, filtered and paged (by offset) by the server (DataTable v2). */
export function grantsSource(owner: string, repo: string, view: SharingView): ServerSource<Grant> {
  const filters = grantsFilters(view);
  return {
    key: [...sharingKey(owner, repo), "grants", filters],
    paging: "offset",
    fetchPage: ({ limit, cursor, offset, signal }) =>
      getJson<GrantList>(
        `${lib(owner, repo)}/grants?${grantsParams(filters, limit, cursor, offset)}`,
        { signal },
      ).then((list) => ({ rows: list.grants, total: list.total, nextCursor: list.next_cursor })),
  };
}

/** The page of grants a view shows (its page and size from the URL, else this browser's size). */
export const grantsPageQueryOptions = (owner: string, repo: string, view: SharingView) => {
  const { page, size } = pageOf(view, GRANTS_TABLE);
  return pageQueryOptions(grantsSource(owner, repo, view), page, size);
};

/** Give a user or a group a role, replacing the one they had. */
export const putGrant = (owner: string, repo: string, grant: GrantRequest) =>
  sendJson<GrantsNow>("PUT", `${lib(owner, repo)}/grants`, grant);

/** Take a user's or a group's role away. */
export const revokeGrant = (owner: string, repo: string, kind: SubjectKind, subject: string) =>
  sendJson<GrantsNow>("DELETE", `${lib(owner, repo)}/grants/${kind}/${seg(subject)}`);

/** Hand the library over: the user becomes its creator, the caller stays an admin. */
export const transferLibrary = (owner: string, repo: string, username: string) =>
  sendJson<GrantsNow>("POST", `${lib(owner, repo)}/transfer`, { username });
