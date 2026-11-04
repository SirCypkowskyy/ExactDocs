import { queryOptions } from "@tanstack/react-query";
import type { components } from "./api-schema";
import { getJson } from "./http";

export type RepositoryRefs = components["schemas"]["RepositoryRefs"];

/** What the ref picker shows: the default first, then branches, tags, and a free-text escape. */
export type RefChoice =
  | { kind: "default" }
  | { kind: "branch"; name: string }
  | { kind: "tag"; name: string }
  | { kind: "other" };

export const encodeChoice = (c: RefChoice) =>
  c.kind === "default" || c.kind === "other" ? c.kind : `${c.kind}:${c.name}`;

export function decodeChoice(value: string): RefChoice {
  if (value === "other") return { kind: "other" };
  const i = value.indexOf(":");
  if (i > 0) {
    const kind = value.slice(0, i);
    if (kind === "branch" || kind === "tag") return { kind, name: value.slice(i + 1) };
  }
  return { kind: "default" };
}

/** The `ref` to send: null means the default branch. */
export function refToSend(choice: RefChoice, typed: string): string | null {
  if (choice.kind === "other") return typed.trim() || null;
  return choice.kind === "default" ? null : choice.name;
}

export function filterRefs<T extends { name: string }>(refs: readonly T[], query: string): T[] {
  const q = query.trim().toLowerCase();
  return q ? refs.filter((r) => r.name.toLowerCase().includes(q)) : [...refs];
}

/** The branches and tags of a repository, for a picker. */
export const repositoryRefsQueryOptions = (url: string) =>
  queryOptions({
    queryKey: ["repositories", "refs", url] as const,
    queryFn: ({ signal }) =>
      getJson<RepositoryRefs>(`/v1/repositories/refs?url=${encodeURIComponent(url)}`, { signal }),
    staleTime: 60_000,
  });
