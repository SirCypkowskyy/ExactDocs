import type { components } from "@/shared/lib/api-schema";

export type Library = components["schemas"]["LibrarySummary"];
export type LibrariesResponse = components["schemas"]["LibraryList"];
export type Job = components["schemas"]["JobSummary"];
export type JobList = components["schemas"]["JobList"];

/** What the newest job of a library says about its sync. */
export type Sync =
  | { kind: "none" }
  | { kind: "running"; job: Job }
  | { kind: "failed"; job: Job }
  | { kind: "ok"; job: Job };

/** Jobs come newest first; an old failure that a later job fixed is not an error. */
export function syncOf(jobs: readonly Job[]): Sync {
  const job = jobs[0];
  if (!job) return { kind: "none" };
  if (job.state === "queued" || job.state === "running") return { kind: "running", job };
  return { kind: job.state === "failed" ? "failed" : "ok", job };
}

/** The default version first, the rest as the API sorted them. */
export function orderedVersions(library: Library): string[] {
  const rest = library.versions.filter((v) => v !== library.default_version);
  return library.default_version ? [library.default_version, ...rest] : rest;
}
