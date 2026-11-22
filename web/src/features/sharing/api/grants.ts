import { infiniteQueryOptions, keepPreviousData } from "@tanstack/react-query";
import { getJson, sendJson } from "@/shared/lib/http";
import type { GrantList, GrantRequest, GrantsNow, SubjectKind } from "../model/grant";
import { grantsParams, type SharingView } from "../model/grants-view";

const seg = encodeURIComponent;
const lib = (owner: string, repo: string) => `/v1/libraries/${seg(owner)}/${seg(repo)}` as const;

/** The root of one library's sharing queries: every change invalidates it. */
export const sharingKey = (owner: string, repo: string) => ["sharing", owner, repo] as const;

/** The grants a view asks for, a page at a time, sorted and filtered by the server. */
export const grantsQueryOptions = (owner: string, repo: string, view: SharingView) =>
  infiniteQueryOptions({
    queryKey: [...sharingKey(owner, repo), "grants", view] as const,
    queryFn: ({ signal, pageParam }) =>
      getJson<GrantList>(`${lib(owner, repo)}/grants?${grantsParams(view, pageParam)}`, {
        signal,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
    // A 403 (not an admin of the library) or a 404 will not change by asking again.
    retry: false,
  });

/** Give a user or a group a role, replacing the one they had. */
export const putGrant = (owner: string, repo: string, grant: GrantRequest) =>
  sendJson<GrantsNow>("PUT", `${lib(owner, repo)}/grants`, grant);

/** Take a user's or a group's role away. */
export const revokeGrant = (owner: string, repo: string, kind: SubjectKind, subject: string) =>
  sendJson<GrantsNow>("DELETE", `${lib(owner, repo)}/grants/${kind}/${seg(subject)}`);

/** Hand the library over: the user becomes its creator, the caller stays an admin. */
export const transferLibrary = (owner: string, repo: string, username: string) =>
  sendJson<GrantsNow>("POST", `${lib(owner, repo)}/transfer`, { username });
