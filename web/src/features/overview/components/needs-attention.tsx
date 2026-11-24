import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, CircleCheck, Cpu, ShieldAlert } from "lucide-react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Badge } from "@/shared/ui/badge";
import { StateBadge } from "@/shared/ui/data-table/cells";
import { LibraryMark } from "@/shared/ui/library-mark";
import { Meter } from "@/shared/ui/meter";
import { EmptyState, Section } from "@/shared/ui/page";
import { Skeleton } from "@/shared/ui/skeleton";
import { aiUsageQueryOptions, FAILING_SHOWN, failingLibrariesQueryOptions } from "../api/overview";
import { overviewMessages } from "../messages";
import { type BudgetAlert, budgetAlerts, type LibrarySummary } from "../model/overview";
import { BlockProblem } from "./block-problem";

type M = (typeof overviewMessages)["en"]["attention"];

const row = "flex flex-wrap items-center gap-x-3 gap-y-2 py-3";
const link =
  "inline-flex min-h-11 items-center gap-1 rounded-sm text-body font-medium underline-offset-4 outline-none fine:min-h-0 focus-visible:ring-2 focus-visible:ring-ring can-hover:hover:underline";

const scopeName = (t: M, a: BudgetAlert) => {
  switch (a.scope) {
    case "instance":
      return t.scopes.instance;
    case "embedding":
      return t.scopes.embedding;
    case "library":
      return t.scopes.library(a.id);
    default:
      return t.scopes.user(a.id);
  }
};

/** The list's frame while it loads. */
export function NeedsAttentionSkeleton() {
  return (
    <ul className="divide-y divide-rule">
      {[0, 1, 2].map((i) => (
        <li key={i} className={row}>
          <Skeleton className="size-6" />
          <Skeleton className="h-4 w-40" />
          <Skeleton className="ml-auto h-4 w-24" />
        </li>
      ))}
    </ul>
  );
}

/** A library whose latest sync failed: its mark and ID, the state, and its failed jobs. */
function FailingRow({ library, t }: { library: LibrarySummary; t: M }) {
  const [, owner = "", repo = ""] = library.id.split("/");
  return (
    <li className={row}>
      <LibraryMark id={library.id} logo={library.logo} size="sm" />
      <Link
        to="/libraries/$owner/$repo"
        params={{ owner, repo }}
        className={cn(link, "font-mono text-mono")}
      >
        {library.id}
      </Link>
      <StateBadge state="failed" label={t.syncFailed} />
      <Link
        to="/jobs"
        search={{ library: library.id, state: ["failed"] }}
        aria-label={t.failedJobsOf(library.id)}
        className={cn(link, "ml-auto text-muted-foreground")}
      >
        {t.failedJobs}
        <ArrowRight aria-hidden="true" data-icon-motion="forward" className="size-4" />
      </Link>
    </li>
  );
}

/** A budget that is reached or near its ceiling, with how much of it is used. */
function BudgetRow({ alert, t }: { alert: BudgetAlert; t: M }) {
  const name = scopeName(t, alert);
  return (
    <li className={row}>
      <Cpu aria-hidden="true" className="size-4 flex-none text-muted-foreground" />
      <span className="min-w-0 flex-1 basis-56 text-body">
        {alert.reached
          ? t.budgetReached(name, alert.window)
          : t.budget(name, alert.window, alert.used)}
      </span>
      <Meter
        role="meter"
        value={alert.used}
        label={t.budgetMeter(name)}
        tone={alert.reached ? "destructive" : "warning"}
        className="w-24"
      />
      <Link to="/ai" className={cn(link, "text-muted-foreground")}>
        {t.openAi}
        <ArrowRight aria-hidden="true" data-icon-motion="forward" className="size-4" />
      </Link>
    </li>
  );
}

function AttentionList({
  libraries,
  total,
  alerts,
  t,
}: {
  libraries: readonly LibrarySummary[];
  total: number;
  alerts: readonly BudgetAlert[];
  t: M;
}) {
  const shown = libraries.slice(0, FAILING_SHOWN);
  const more = Math.max(0, total - shown.length);
  return (
    <ul className="divide-y divide-rule">
      {shown.map((library) => (
        <FailingRow key={library.id} library={library} t={t} />
      ))}
      {more > 0 && (
        <li className={row}>
          <span className="text-body text-muted-foreground">{t.moreFailing(more)}</span>
          <Link
            to="/jobs"
            search={{ state: ["failed"] }}
            className={cn(link, "ml-auto text-muted-foreground")}
          >
            {t.allFailed}
            <ArrowRight aria-hidden="true" data-icon-motion="forward" className="size-4" />
          </Link>
        </li>
      )}
      {alerts.map((a) => (
        <BudgetRow key={`${a.scope}:${a.id}:${a.window}`} alert={a} t={t} />
      ))}
    </ul>
  );
}

/**
 * What an operator should look at, as a list rather than a chart (blocks-map §5.2): libraries
 * whose latest sync failed, and AI budgets that are reached or near their ceiling.
 */
export function NeedsAttention() {
  const t = useMessages(overviewMessages).attention;
  const failing = useQuery(failingLibrariesQueryOptions());
  const ai = useQuery(aiUsageQueryOptions());
  const alerts = ai.data ? budgetAlerts(ai.data) : [];
  const total = failing.data?.total ?? 0;
  const count = total + alerts.length;
  const pending = failing.isPending || ai.isPending;
  const retry = () => {
    if (failing.isError) void failing.refetch();
    if (ai.isError) void ai.refetch();
  };
  const problem = (failing.isError || ai.isError) && (
    <BlockProblem message={t.failed} onRetry={retry} />
  );
  const body = pending ? (
    <NeedsAttentionSkeleton />
  ) : count > 0 ? (
    <AttentionList libraries={failing.data?.libraries ?? []} total={total} alerts={alerts} t={t} />
  ) : (
    !problem && (
      <EmptyState icon={<CircleCheck aria-hidden="true" />} title={t.none}>
        {t.noneBody}
      </EmptyState>
    )
  );
  return (
    <Section
      id="attention"
      title={
        <>
          {t.title}
          {!pending && count > 0 && <Badge count>{count}</Badge>}
        </>
      }
      icon={<ShieldAlert />}
    >
      <div className="flex flex-col gap-3">
        {!pending && problem}
        {body}
      </div>
    </Section>
  );
}
