import type { InfiniteData, UseInfiniteQueryResult } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useId, useState } from "react";
import { absoluteTime, absoluteTimeWithZone } from "@/shared/lib/time";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { EmptyState } from "@/shared/ui/page";
import { SelectField } from "@/shared/ui/select-field";
import { Skeleton } from "@/shared/ui/skeleton";
import {
  type AccessEvent,
  type AccessLogPage,
  type AccessLogView,
  CHANGE_LABELS,
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
  return (
    <p className="[overflow-wrap:anywhere]">
      {describeEvent(event).map((part) => (
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
  const [library, setLibrary] = useState(view.library ?? "");
  const invalid = library.trim() !== "" && !isLibraryId(library);
  return (
    <search className="mb-4 flex flex-wrap items-end gap-3">
      <div className="w-60">
        <SelectField
          id={`${id}-change`}
          label="Show"
          value={view.change ?? ""}
          onChange={(e) => onView({ ...view, change: (e.target.value || undefined) as Change })}
        >
          <option value="">Every change</option>
          {Object.entries(CHANGE_LABELS).map(([value, label]) => (
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
            Library
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
              Filter
            </Button>
          </div>
          <p id={`${id}-library-hint`} className="text-small text-muted-foreground">
            {invalid
              ? "Write the library's ID as /owner/repo."
              : "The full ID; removed libraries keep their log."}
          </p>
        </form>
      )}
    </search>
  );
}

/** The access log: who changed access, how and when, newest first, a page at a time. */
export function AccessLogList({ log, view, onView, everyLibrary = false }: Props) {
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
          {explainAccessLogError(log.error)}
        </p>
        <Button variant="ghost" onClick={() => log.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  if (total === 0 && !filtered) {
    return (
      <EmptyState icon={<History aria-hidden="true" />} title="Nothing recorded yet">
        Creating, sharing, unsharing and removing a library is recorded here, with who did it and
        when.
      </EmptyState>
    );
  }
  return (
    <div>
      <Toolbar view={view} onView={onView} everyLibrary={everyLibrary} />
      {events.length === 0 ? (
        <EmptyState title="No changes match" className="max-w-2xl">
          <p>Nothing recorded matches these filters.</p>
          <Button variant="ghost" className="mt-3" onClick={() => onView({})}>
            Clear filters
          </Button>
        </EmptyState>
      ) : (
        <>
          <ol aria-label="Access changes, newest first" className="divide-y divide-rule border-y">
            {events.map((event) => (
              <li
                key={event.id}
                className="row-in flex flex-col gap-1 py-3 sm:grid sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-x-4"
              >
                <time
                  dateTime={event.at}
                  title={absoluteTimeWithZone(event.at)}
                  className="text-small text-muted-foreground tabular-nums sm:pt-0.5"
                >
                  {absoluteTime(event.at)}
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
            <p className="num">
              Showing {events.length} of {total}
            </p>
            {log.hasNextPage && (
              <Button
                variant="outline"
                onClick={() => void log.fetchNextPage()}
                disabled={log.isFetchingNextPage}
              >
                Load more
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function AccessLogSkeleton() {
  return (
    <div aria-busy="true">
      <span className="sr-only">Loading the access log</span>
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
