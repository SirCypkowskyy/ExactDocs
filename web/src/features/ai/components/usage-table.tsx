import { useQuery } from "@tanstack/react-query";
import { useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { Gauge, Layers, LibraryBig, type LucideIcon, Server, UserRound } from "lucide-react";
import { useMemo } from "react";
import { common, type Language, useLanguage, useMessages } from "@/shared/lib/i18n";
import { absoluteTimeWithZone } from "@/shared/lib/time";
import { LibraryCell } from "@/shared/ui/data-table/cells";
import { DataTable } from "@/shared/ui/data-table/data-table";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import { type TableFilter, useDataTable } from "@/shared/ui/data-table/use-data-table";
import { Meter } from "@/shared/ui/meter";
import { Section } from "@/shared/ui/page";
import { aiUsageQueryOptions } from "../api/ai";
import { messages } from "../messages";
import {
  BUDGET_NEAR,
  type Budget,
  budgetUsed,
  budgetWords,
  explainAiError,
  ownBudgetNote,
  type ScopeUsage,
  scopeName,
} from "../model/ai";
import {
  BUDGET_STATES,
  budgetState,
  mostUsed,
  parseUsageView,
  SCOPE_KINDS,
  type ScopeKind,
  USAGE_TABLE,
} from "../model/usage-view";

/*
 * What AI calls spent per scope, and the budgets left (blocks-map §2.3, "AI usage"): DataTable v2
 * in client mode over the one `GET /ai/usage`, sorted, filtered and paged here with the view in
 * the URL. A chart of the spend history joins it later (#511).
 */

type Messages = (typeof messages)["en"];

const SCOPE_ICONS: Record<ScopeKind, LucideIcon> = {
  instance: Server,
  embedding: Layers,
  library: LibraryBig,
  user: UserRound,
};

const kindOf = (s: ScopeUsage): ScopeKind =>
  (SCOPE_KINDS as readonly string[]).includes(s.scope) ? (s.scope as ScopeKind) : "user";

/** A library by its mark and ID (a link to it); anything else by its icon and its name. */
function ScopeCell({ scope: s }: { scope: ScopeUsage }) {
  const language = useLanguage();
  if (s.scope === "library") return <LibraryCell id={s.id} />;
  const Icon = SCOPE_ICONS[kindOf(s)];
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="inline-flex size-6 flex-none items-center justify-center rounded-full bg-secondary text-muted-foreground">
        <Icon aria-hidden="true" className="size-3.5" />
      </span>
      <span className="font-medium [overflow-wrap:anywhere]">{scopeName(s, language)}</span>
    </span>
  );
}

/** The money leads; tokens and calls sit under it, so a column is one figure to scan. */
function Spent({ spent: s }: { spent: ScopeUsage["day"] }) {
  const t = useMessages(messages);
  // Local models cost nothing: their tokens are shown, but no token budget counts them.
  return (
    <span className="block tabular-nums">
      <span className="block font-medium">{t.usd(s.usd)}</span>
      <span className="block text-small text-muted-foreground">
        {t.usage.spent(s.tokens, s.local_tokens, s.requests, s.unpriced_requests)}
      </span>
    </span>
  );
}

function BudgetItem({ budget: b }: { budget: Budget }) {
  const t = useMessages(messages);
  const language = useLanguage();
  const note = ownBudgetNote(b, language);
  const used = budgetUsed(b);
  const tone = b.reached ? "destructive" : used >= BUDGET_NEAR ? "warning" : "route";
  return (
    <li>
      <span className={b.reached ? "font-medium text-destructive" : undefined}>
        {budgetWords(b, language)}
        {b.reached && t.usage.reachedUntil(absoluteTimeWithZone(b.resets_at, language))}
      </span>
      <Meter
        role="meter"
        value={used}
        tone={tone}
        label={t.usage.used(b.window === "day" ? "day" : "month")}
        className="mt-1.5"
      />
      {note && <span className="mt-1 block text-small text-muted-foreground">{note}</span>}
    </li>
  );
}

function Budgets({ scope: s }: { scope: ScopeUsage }) {
  const c = useMessages(common);
  if (s.budgets.length === 0) return <span className="text-muted-foreground">{c.none}</span>;
  return (
    <ul className="flex min-w-56 flex-col gap-3">
      {s.budgets.map((b) => (
        <BudgetItem key={b.window} budget={b} />
      ))}
    </ul>
  );
}

// Built once per language: a cell is rendered as a component, so a new function would remount
// it. `scope` and `budget` are hidden columns that only feed their filters.
const columnsOf = (t: Messages, language: Language): ColumnDef<ScopeUsage>[] => [
  {
    id: "name",
    // What the search box searches and the column sorts by.
    accessorFn: (s) => scopeName(s, language),
    header: t.usage.scope,
    enableHiding: false,
    meta: { priority: 1, skeleton: "avatar" },
    cell: ({ row }) => <ScopeCell scope={row.original} />,
  },
  {
    id: "scope",
    accessorFn: kindOf,
    header: t.usage.kind,
    enableHiding: false,
    enableSorting: false,
    enableGlobalFilter: false,
  },
  {
    id: "day",
    accessorFn: (s) => s.day.usd,
    header: t.usage.today,
    sortDescFirst: true,
    enableGlobalFilter: false,
    meta: { priority: 2, align: "end", skeleton: "number" },
    cell: ({ row }) => <Spent spent={row.original.day} />,
  },
  {
    id: "month",
    accessorFn: (s) => s.month.usd,
    header: t.usage.thisMonth,
    sortDescFirst: true,
    enableGlobalFilter: false,
    meta: { priority: 2, align: "end", skeleton: "number" },
    cell: ({ row }) => <Spent spent={row.original.month} />,
  },
  {
    id: "used",
    accessorFn: mostUsed,
    header: t.usage.budgets,
    sortDescFirst: true,
    enableGlobalFilter: false,
    meta: { priority: 3, skeleton: "meter" },
    cell: ({ row }) => <Budgets scope={row.original} />,
  },
  {
    id: "budget",
    accessorFn: budgetState,
    header: t.usage.budgetFilter,
    enableHiding: false,
    enableSorting: false,
    enableGlobalFilter: false,
  },
];

const filtersOf = (t: Messages): TableFilter[] => [
  {
    id: "scope",
    title: t.usage.kind,
    options: SCOPE_KINDS.map((k) => ({
      value: k,
      label: t.usage.scopeKinds[k],
      icon: SCOPE_ICONS[k],
    })),
  },
  {
    id: "budget",
    title: t.usage.budgetFilter,
    options: BUDGET_STATES.map((b) => ({ value: b, label: t.usage.budgetStates[b] })),
  },
];

const HIDDEN = { scope: false, budget: false };

export function UsageSection() {
  const t = useMessages(messages);
  const language = useLanguage();
  const view = parseUsageView(useSearch({ strict: false }) as Record<string, unknown>);
  const usage = useQuery(aiUsageQueryOptions());
  // The same request: its scopes are the table's rows.
  const scopes = useQuery({ ...aiUsageQueryOptions(), select: (data) => data.scopes });
  const columns = useMemo(() => columnsOf(t, language), [t, language]);
  const filters = useMemo(() => filtersOf(t), [t]);
  const model = useDataTable({
    config: USAGE_TABLE,
    search: view,
    columns,
    getRowId: (s) => `${s.scope}:${s.id}`,
    filters,
    query: scopes,
    initialColumnVisibility: HIDDEN,
  });
  return (
    <Section id="usage" icon={<Gauge />} title={t.usage.title} description={t.usage.description}>
      {usage.data && (
        <p className="mb-3 text-body text-muted-foreground">
          {t.usage.searchesPerMinute}
          {usage.data.llm_searches_per_minute ?? t.usage.notLimited}
        </p>
      )}
      <DataTableToolbar
        model={model}
        search={{ label: t.usage.find, placeholder: t.usage.findPlaceholder }}
      />
      <DataTable
        model={model}
        label={t.usage.table}
        rowLabel={(s) => scopeName(s, language)}
        empty={{ icon: Gauge, title: t.usage.empty }}
        noMatch={{ title: t.usage.noMatch }}
        errorMessage={usage.isError ? explainAiError(usage.error, language) : undefined}
      />
      <DataTablePagination model={model} />
    </Section>
  );
}
