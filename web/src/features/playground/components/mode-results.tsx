import { useQuery } from "@tanstack/react-query";
import { useId } from "react";
import { HttpError } from "@/shared/lib/http";
import { cn } from "@/shared/lib/utils";
import { EmptyState } from "@/shared/ui/page";
import { pill, pillTone } from "@/shared/ui/recipes";
import { playgroundSearchQueryOptions } from "../api/playground-queries";
import {
  fallbackSentence,
  MODE_LABEL,
  type PlaygroundHit,
  type PlaygroundMode,
  rankLabels,
} from "../model/playground";
import { Notice, ResultHead, ResultsSkeleton, resultCard, resultList } from "./parts";

function Hit({ hit, place }: { hit: PlaygroundHit; place: number }) {
  return (
    <li className={cn(resultCard, "row-in")}>
      <ResultHead
        library={hit.library}
        version={hit.version}
        articlePath={hit.article_path}
        anchor={hit.anchor}
        headingPath={hit.heading_path}
      />
      <p className="mt-2 text-body whitespace-pre-wrap [overflow-wrap:anywhere]">{hit.snippet}</p>
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-small text-muted-foreground">
        <span className="font-medium text-foreground tabular-nums">{place}.</span>
        <span className="tabular-nums" title="Score in the mode that answered">
          score {hit.score.toFixed(4)}
        </span>
        {rankLabels(hit).map((label) => (
          <span key={label} className={cn(pill, pillTone.neutral, "font-mono")}>
            {label}
          </span>
        ))}
      </div>
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
      <h2 id={headingId} className="text-section font-semibold">
        {MODE_LABEL[mode]}
      </h2>
      {error && (
        <Notice tone="error">
          {error instanceof HttpError && error.code === "mode_unavailable"
            ? `Unavailable: ${error.message}`
            : error.message}
        </Notice>
      )}
      {!error && !data && isFetching && (
        <>
          <p role="status" className="text-body text-muted-foreground">
            Searching…
          </p>
          <ResultsSkeleton />
        </>
      )}
      {data && (
        <>
          <p className="text-body text-muted-foreground">
            Answered by <span className="font-medium text-foreground">{data.retrieval_mode}</span>
            {" · "}
            {data.results.length} result{data.results.length === 1 ? "" : "s"} from{" "}
            {data.libraries_searched} librar{data.libraries_searched === 1 ? "y" : "ies"}
          </p>
          {data.fallback_reason && (
            <Notice tone="note">
              {fallbackSentence(data.fallback_reason)}{" "}
              <span className="font-mono text-mono">({data.fallback_reason})</span>
            </Notice>
          )}
          {data.libraries_without_vectors.length > 0 && (
            <p className="text-body text-muted-foreground">
              Not in the vector ranking (AI off or not embedded yet):{" "}
              {data.libraries_without_vectors.join(", ")}
            </p>
          )}
          {data.results.length === 0 ? (
            <EmptyState title="No results">Try other words, or choose more libraries.</EmptyState>
          ) : (
            <ol aria-label={`${MODE_LABEL[mode]} results`} className={resultList}>
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
