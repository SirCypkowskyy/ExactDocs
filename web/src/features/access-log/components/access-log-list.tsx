import type { InfiniteData, UseInfiniteQueryResult } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useId, useState } from "react";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { absoluteTime, absoluteTimeWithZone } from "@/shared/lib/time";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { EmptyState } from "@/shared/ui/page";
import { SelectField } from "@/shared/ui/select-field";
import { Skeleton } from "@/shared/ui/skeleton";
import { messages } from "../messages";
import {
  type AccessEvent,
  type AccessLogPage,
  type AccessLogView,
  type Change,
  describeEvent,
  explainAccessLogError,
  isLibraryId,
} from "../model/access-log";

interface Props {
  log: UseInfiniteQueryResult<InfiniteData<AccessLogPage>>;
  view: AccessLogView;
  onView: (view: AccessLogView) => void;
  /** The operators' log of every library: a library filter, and each event names its library. */
  everyLibrary?: boolean;
}

function EventSentence({ event }: { event: AccessEvent }) {
  const language = useLanguage();
  return (
    <p className="[overflow-wrap:anywhere]">
      {describeEvent(event, language).map((part) => (
        <span
          key={part.key}
          className={cn(
            part.kind === "person" && "font-medium",
            part.kind === "group" && "font-mono text-small font-medium",
            part.kind === "role" && "rounded-sm bg-accent px-1.5 py-0.5 text-small",
          )}
        >
          {part.text}
        </span>
      ))}
    </p>
  );
}

function Toolbar({ view, onView, everyLibrary }: Omit<Props, "log">) {
  const id = useId();
  const t = useMessages(messages).list;
  const [library, setLibrary] = useState(view.library ?? "");
  const invalid = library.trim() !== "" && !isLibraryId(library);
  return (
    <search className="mb-4 flex flex-wrap items-end gap-3">
      <div className="w-60">
        <SelectField
          id={`${id}-change`}
          label={t.show}
          value={view.change ?? ""}
          onChange={(e) => onView({ ...view, change: (e.target.value || undefined) as Change })}
        >
          <option value="">{t.everyChange}</option>
          {Object.entries(t.changes).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>
      </div>
      {everyLibrary && (
        <form
          className="flex min-w-0 flex-1 basis-60 flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!invalid) onView({ ...view, library: library.trim() || undefined });
          }}
        >
          <label htmlFor={`${id}-library`} className="text-body font-medium">
            {t.library}
          </label>
          <div className="flex gap-2">
            <Input
              id={`${id}-library`}
              type="search"
              value={library}
              aria-invalid={invalid || undefined}
              aria-describedby={`${id}-library-hint`}
              onChange={(e) => {
                setLibrary(e.target.value);
                if (!e.target.value.trim() && view.library) onView({ ...view, library: undefined });
              }}
              placeholder="/owner/repo"
              className="font-mono"
            />
            <Button type="submit" variant="outline">
              {t.filter}
            </Button>
          </div>
          <p id={`${id}-library-hint`} className="text-small text-muted-foreground">
            {invalid ? t.libraryInvalid : t.libraryHint}
          </p>
        </form>
      )}
    </search>
  );
}

/** The access log: who changed access, how and when, newest first, a page at a time. */
export function AccessLogList({ log, view, onView, everyLibrary = false }: Props) {
  const language = useLanguage();
  const t = useMessages(messages).list;
  const c = useMessages(common);
  const events = log.data?.pages.flatMap((p) => p.events) ?? [];
  const total = log.data?.pages.at(-1)?.total ?? 0;
  const filtered = Boolean(view.change || view.library);
  if (log.isPending) return <AccessLogSkeleton />;
  if (log.isError && !log.data) {
    return (
      <div
        role="alert"
        className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-lg bg-destructive-soft py-1.5 pr-1.5 pl-4"
      >
        <p className="text-body font-medium text-destructive-ink">
          {explainAccessLogError(log.error, language)}
        </p>
        <Button variant="ghost" onClick={() => log.refetch()}>
          {c.retry}
        </Button>
      </div>
    );
  }
  if (total === 0 && !filtered) {
    return (
      <EmptyState icon={<History aria-hidden="true" />} title={t.emptyTitle}>
        {t.emptyBody}
      </EmptyState>
    );
  }
  return (
    <div>
      <Toolbar view={view} onView={onView} everyLibrary={everyLibrary} />
      {events.length === 0 ? (
        <EmptyState title={t.noMatchTitle} className="max-w-2xl">
          <p>{t.noMatch}</p>
          <Button variant="ghost" className="mt-3" onClick={() => onView({})}>
            {t.clearFilters}
          </Button>
        </EmptyState>
      ) : (
        <>
          <ol aria-label={t.label} className="divide-y divide-rule border-y">
            {events.map((event) => (
              <li
                key={event.id}
                className="row-in flex flex-col gap-1 py-3 sm:grid sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-x-4"
              >
                <time
                  dateTime={event.at}
                  title={absoluteTimeWithZone(event.at, language)}
                  className="text-small text-muted-foreground tabular-nums sm:pt-0.5"
                >
                  {absoluteTime(event.at, language)}
                </time>
                <div className="min-w-0">
                  <EventSentence event={event} />
                  {everyLibrary && (
                    <p className="mt-0.5 font-mono text-small text-muted-foreground [overflow-wrap:anywhere]">
                      {event.library}
                    </p>
                  )}
                </div>
              </li>
            ))}
            {log.isFetchingNextPage && (
              <li aria-hidden="true" className="py-3">
                <Skeleton className="h-6 w-full" />
              </li>
            )}
          </ol>
          <div className="flex items-center gap-3 pt-4 text-small text-muted-foreground">
            <p className="num">{t.showing(events.length, total)}</p>
            {log.hasNextPage && (
              <Button
                variant="outline"
                onClick={() => void log.fetchNextPage()}
                disabled={log.isFetchingNextPage}
              >
                {t.loadMore}
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function AccessLogSkeleton() {
  const t = useMessages(messages).list;
  return (
    <div aria-busy="true">
      <span className="sr-only">{t.loading}</span>
      <div aria-hidden="true" className="divide-y divide-rule border-y border-border">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex gap-4 py-3">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-4 w-72" />
          </div>
        ))}
      </div>
    </div>
  );
}
