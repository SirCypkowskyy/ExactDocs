import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId } from "react";
import { HttpError } from "@/shared/lib/http";
import { playgroundSearchQueryOptions } from "../api/playground-queries";
import {
  fallbackSentence,
  MODE_LABEL,
  type PlaygroundHit,
  type PlaygroundMode,
  rankLabels,
  splitLibrary,
} from "../model/playground";

function Hit({ hit, place }: { hit: PlaygroundHit; place: number }) {
  const { owner, repo } = splitLibrary(hit.library);
  return (
    <li className="relative space-y-1 rounded-md border border-border p-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span className="font-medium text-foreground tabular-nums">{place}.</span>
        <span className="font-medium text-foreground">{hit.library}</span>
        <span>
          <span className="sr-only">version </span>
          {hit.version}
        </span>
        <span className="tabular-nums" title="Score in the mode that answered">
          score {hit.score.toFixed(4)}
        </span>
        {rankLabels(hit).map((label) => (
          <span
            key={label}
            className="rounded bg-secondary px-1.5 py-0.5 font-mono text-secondary-foreground"
          >
            {label}
          </span>
        ))}
      </div>
      <Link
        to="/libraries/$owner/$repo"
        params={{ owner, repo }}
        search={{ version: hit.version, path: hit.article_path }}
        {...(hit.anchor ? { hash: hit.anchor } : {})}
        className="block rounded-md text-sm font-medium underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
      >
        {hit.heading_path.length > 0 ? hit.heading_path.join(" › ") : hit.article_path}
      </Link>
      <p className="font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">
        {hit.article_path}
      </p>
      <p className="text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">{hit.snippet}</p>
    </li>
  );
}

/** One mode's results for the playground's query: what answered, why, and each result's ranks. */
export function ModeResults({
  q,
  mode,
  libraries,
}: {
  q: string;
  mode: PlaygroundMode;
  libraries: readonly string[];
}) {
  const headingId = useId();
  const { data, error, isFetching } = useQuery(playgroundSearchQueryOptions(q, mode, libraries));
  return (
    <section aria-labelledby={headingId} aria-busy={isFetching} className="min-w-0 space-y-3">
      <h2 id={headingId} className="text-base font-semibold">
        {MODE_LABEL[mode]}
      </h2>
      {error && (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error instanceof HttpError && error.code === "mode_unavailable"
            ? `Unavailable: ${error.message}`
            : error.message}
        </p>
      )}
      {!error && !data && isFetching && <p className="text-sm text-muted-foreground">Searching…</p>}
      {data && (
        <>
          <p className="text-sm text-muted-foreground">
            Answered by <span className="font-medium text-foreground">{data.retrieval_mode}</span>
            {" · "}
            {data.results.length} result{data.results.length === 1 ? "" : "s"} from{" "}
            {data.libraries_searched} librar{data.libraries_searched === 1 ? "y" : "ies"}
          </p>
          {data.fallback_reason && (
            <p className="rounded-md bg-accent px-3 py-2 text-sm">
              {fallbackSentence(data.fallback_reason)}{" "}
              <span className="font-mono text-xs">({data.fallback_reason})</span>
            </p>
          )}
          {data.libraries_without_vectors.length > 0 && (
            <p className="text-sm text-muted-foreground">
              Not in the vector ranking (AI off or not embedded yet):{" "}
              {data.libraries_without_vectors.join(", ")}
            </p>
          )}
          {data.results.length === 0 ? (
            <p className="text-sm text-muted-foreground">No results.</p>
          ) : (
            <ol aria-label={`${MODE_LABEL[mode]} results`} className="space-y-2">
              {data.results.map((hit, i) => (
                <Hit key={`${hit.library}:${hit.chunk_id}`} hit={hit} place={i + 1} />
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}
