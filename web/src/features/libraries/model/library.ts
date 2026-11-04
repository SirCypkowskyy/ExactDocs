import type { components } from "@/shared/lib/api-schema";

export type Library = components["schemas"]["LibrarySummary"];
export type LibrariesResponse = components["schemas"]["LibraryList"];
export type Job = components["schemas"]["JobSummary"];
/** The newest job of one version, without its skipped files (see `/jobs/{id}`). */
export type LatestJob = components["schemas"]["LatestJob"];
export type LatestJobs = components["schemas"]["LatestJobs"];

/** What the newest job of every version of a library says about its sync. */
export type Sync =
  | { kind: "none" }
  | { kind: "running"; job: LatestJob }
  | { kind: "failed"; job: LatestJob; failures: number }
  | { kind: "ok"; skipped: number; job: LatestJob };

const live = (job: LatestJob) => job.state === "queued" || job.state === "running";

/**
 * A failed version stays visible even when another version synced after it; failed beats
 * running beats ok. `jobs` are the newest job per version of one library.
 */
export function syncOf(jobs: readonly LatestJob[]): Sync {
  const failed = jobs.filter((j) => j.state === "failed").sort((a, b) => b.id.localeCompare(a.id));
  const [newestFailure] = failed;
  if (newestFailure) return { kind: "failed", job: newestFailure, failures: failed.length };
  const running = jobs.find(live);
  if (running) return { kind: "running", job: running };
  const [last] = [...jobs].sort((a, b) => b.id.localeCompare(a.id));
  if (!last) return { kind: "none" };
  return { kind: "ok", job: last, skipped: jobs.reduce((n, j) => n + j.skipped, 0) };
}

/** `v2.10.0` -> [2, 10, 0]; null when the ref is not a dotted number. */
function semver(ref: string): number[] | null {
  const m = /^v?(\d+(?:\.\d+)*)/.exec(ref);
  return m?.[1] ? m[1].split(".").map(Number) : null;
}

function byVersionDesc(a: string, b: string): number {
  const x = semver(a);
  const y = semver(b);
  if (x && y) {
    for (let i = 0; i < Math.max(x.length, y.length); i++) {
      const d = (y[i] ?? 0) - (x[i] ?? 0);
      if (d !== 0) return d;
    }
    return 0;
  }
  return x ? -1 : y ? 1 : a.localeCompare(b);
}

/** The default version first, then tags by semver descending, then branches and commits. */
export function orderedVersions(library: Library): string[] {
  const kinds = new Map(library.refs.map((r) => [r.ref, r.kind]));
  const rest = library.versions.filter((v) => v !== library.default_version);
  const tags = rest.filter((v) => (kinds.get(v) ?? "tag") === "tag").sort(byVersionDesc);
  const others = rest.filter((v) => (kinds.get(v) ?? "tag") !== "tag").sort();
  return [...(library.default_version ? [library.default_version] : []), ...tags, ...others];
}

/** Libraries whose sync failed first; otherwise the API's order. */
export function failedFirst<T extends { id: string }>(
  libraries: readonly T[],
  failed: (id: string) => boolean,
): T[] {
  return [...libraries].sort((a, b) => Number(failed(b.id)) - Number(failed(a.id)));
}

export const shortSha = (sha: string) => sha.slice(0, 7);

/** `https://github.com/acme/payments.git` -> `github.com/acme/payments`. */
export function sourceLabel(url: string): string {
  return url
    .replace(/^[a-z+]+:\/\//i, "")
    .replace(/\.git$/, "")
    .replace(/\/$/, "");
}
