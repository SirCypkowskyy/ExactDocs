import { useQuery } from "@tanstack/react-query";
import { Combine, type LucideIcon, SearchX, Waypoints, WholeWord } from "lucide-react";
import { useId } from "react";
import { HttpError } from "@/shared/lib/http";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Badge } from "@/shared/ui/badge";
import { EmptyState } from "@/shared/ui/page";
import { playgroundSearchQueryOptions } from "../api/playground-queries";
import { messages } from "../messages";
import {
  fallbackSentence,
  librariesRanked,
  type PlaygroundHit,
  type PlaygroundMode,
  rankLabels,
} from "../model/playground";
import {
  Notice,
  ResultHead,
  ResultsHeading,
  ResultsSkeleton,
  resultCard,
  resultList,
} from "./parts";

/** Each mode by its icon: keywords, vectors, both. */
const MODE_ICONS: Record<PlaygroundMode, LucideIcon> = {
  bm25: WholeWord,
  vector: Waypoints,
  hybrid: Combine,
};

function Hit({ hit, place }: { hit: PlaygroundHit; place: number }) {
  const t = useMessages(messages);
  const language = useLanguage();
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
        <span className="tabular-nums" title={t.results.scoreTitle}>
          {t.results.score(hit.score)}
        </span>
        {rankLabels(hit, language).map((label) => (
          <Badge key={label} className="font-mono">
            {label}
          </Badge>
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
  const t = useMessages(messages);
  const language = useLanguage();
  const headingId = useId();
  const { data, error, isFetching } = useQuery(playgroundSearchQueryOptions(q, mode, libraries));
  const ranked = data ? librariesRanked(libraries, data) : 0;
  return (
    <section aria-labelledby={headingId} aria-busy={isFetching} className="min-w-0 space-y-3">
      <ResultsHeading id={headingId} icon={MODE_ICONS[mode]}>
        {t.modes[mode]}
      </ResultsHeading>
      {error && (
        <Notice tone="error">
          {error instanceof HttpError && error.code === "mode_unavailable"
            ? t.results.unavailable(error.message)
            : error.message}
        </Notice>
      )}
      {!error && !data && isFetching && (
        <>
          <p role="status" className="text-body text-muted-foreground">
            {t.results.searching}
          </p>
          <ResultsSkeleton />
        </>
      )}
      {data && (
        <>
          <p className="text-body text-muted-foreground">
            {t.results.answeredBy(
              <span className="font-medium text-foreground">{data.retrieval_mode}</span>,
              data.results.length,
              ranked,
            )}
          </p>
          {data.fallback_reason && (
            <Notice tone="note">
              {fallbackSentence(data.fallback_reason, language)}{" "}
              <span className="font-mono text-mono">({data.fallback_reason})</span>
            </Notice>
          )}
          {data.libraries_without_vectors.length > 0 && (
            <p className="text-body text-muted-foreground">
              {t.results.withoutVectors(data.libraries_without_vectors.join(", "))}
            </p>
          )}
          {data.results.length === 0 ? (
            <EmptyState icon={<SearchX aria-hidden="true" />} title={t.results.none}>
              {t.results.noneHint}
            </EmptyState>
          ) : (
            <ol aria-label={t.results.list(t.modes[mode])} className={resultList}>
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
