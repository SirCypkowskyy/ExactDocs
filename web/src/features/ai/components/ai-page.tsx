import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Sparkles } from "lucide-react";
import { toast } from "sonner";
import {
  type AiProvider,
  type AiRole,
  aiProvidersQueryOptions,
  aiRolesQueryOptions,
  ROLE_LABEL,
  THINKING_HINT,
  THINKING_LABEL,
  THINKING_LEVELS,
  type ThinkingLevel,
} from "@/shared/lib/ai-queries";
import { absoluteTime, absoluteTimeWithZone } from "@/shared/lib/time";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { EmptyState, Page, PageHeader, Section } from "@/shared/ui/page";
import { pill, pillTone } from "@/shared/ui/recipes";
import { SelectField } from "@/shared/ui/select-field";
import { Skeleton } from "@/shared/ui/skeleton";
import {
  aiUsageQueryOptions,
  checkProvider,
  embeddingProgressQueryOptions,
  setRoleThinking,
} from "../api/ai";
import {
  BUDGET_NEAR,
  type Budget,
  budgetUsed,
  budgetWords,
  checkWords,
  count,
  explainAiError,
  keyWords,
  originWords,
  ownBudgetNote,
  percent,
  type ScopeUsage,
  type SpaceProgress,
  scopeName,
  usd,
} from "../model/ai";
import { Meter } from "./meter";

const SKELETON_ROWS = [0, 1, 2, 3] as const;
const card = "rounded-lg border border-border bg-raised";

/** The instance's AI: providers and roles, embedding progress and spend (admins). */
export function AiPage() {
  const title = usePageTitle("AI");
  return (
    <Page>
      <PageHeader
        title="AI"
        headingRef={title}
        description="The providers and models this instance uses, how far embedding has got, and what AI calls spent. Keys are never shown."
      />
      <div className="flex flex-col gap-12">
        <div className="grid items-start gap-12 lg:grid-cols-2 lg:gap-8">
          <ProvidersSection />
          <EmbeddingSection />
        </div>
        <UsageSection />
      </div>
    </Page>
  );
}

/** A block that failed to load: one sentence, inside the block, with a way to retry. */
function Problem({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-lg bg-destructive-soft py-1.5 pr-1.5 pl-4"
    >
      <p className="text-body font-medium text-destructive-ink">{explainAiError(error)}</p>
      <Button variant="ghost" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

function CardSkeleton({ label, rows = 2 }: { label: string; rows?: number }) {
  return (
    <div aria-busy="true" className="flex flex-col gap-3">
      <span className="sr-only">{label}</span>
      {SKELETON_ROWS.slice(0, rows).map((i) => (
        <div key={i} className={cn(card, "flex flex-col gap-2.5 p-4")}>
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-64 max-w-full" />
        </div>
      ))}
    </div>
  );
}

function ProvidersSection() {
  const providers = useQuery(aiProvidersQueryOptions());
  const roles = useQuery(aiRolesQueryOptions());
  return (
    <Section
      id="providers"
      title="Providers and roles"
      description="Each role is a model of a provider profile. Check a profile to make one small call per role that uses it."
    >
      <div className="flex flex-col gap-4">
        {roles.isError ? (
          <Problem error={roles.error} onRetry={() => roles.refetch()} />
        ) : roles.data ? (
          <RoleList roles={roles.data} />
        ) : (
          <div aria-busy="true" className={cn(card, "flex flex-col gap-3 p-4")}>
            <span className="sr-only">Loading the roles</span>
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-5 w-full" />
            ))}
          </div>
        )}
        {providers.isPending ? (
          <CardSkeleton label="Loading the providers" />
        ) : providers.isError ? (
          <Problem error={providers.error} onRetry={() => providers.refetch()} />
        ) : providers.data.length === 0 ? (
          <EmptyState icon={<Sparkles aria-hidden="true" />} title="No provider is configured">
            Searches use BM25 and nothing leaves the instance. Add a provider profile to the
            instance configuration to turn on embeddings or an LLM.
          </EmptyState>
        ) : (
          <ul className="flex flex-col gap-3">
            {providers.data.map((p) => (
              <ProviderCard key={p.name} provider={p} />
            ))}
          </ul>
        )}
      </div>
    </Section>
  );
}

function RoleList({ roles }: { roles: readonly AiRole[] }) {
  return (
    <dl className={cn(card, "grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-2.5 p-4 text-body")}>
      {roles.map((r) => (
        <div key={r.role} className="contents">
          <dt className="font-medium">{ROLE_LABEL[r.role]}</dt>
          <dd className="[overflow-wrap:anywhere]">
            {r.model ? (
              <>
                <span className="font-mono text-small">{r.model}</span>
                {r.source === "llm" && <span className="text-muted-foreground"> (the LLM's)</span>}
                {!r.profile_exists && (
                  <span className="text-destructive"> (its profile does not exist)</span>
                )}
              </>
            ) : (
              <span className="text-muted-foreground">
                Not set. Choose its model in the instance configuration.
              </span>
            )}
            {(r.role === "llm" || r.role === "judge") && <RoleThinking role={r} name={r.role} />}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** The thinking level of the `llm` or `judge` role: set here, unless the configuration sets it. */
function RoleThinking({ role, name }: { role: AiRole; name: "llm" | "judge" }) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (thinking: ThinkingLevel | null) => setRoleThinking(name, thinking),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: aiRolesQueryOptions().queryKey }),
  });
  const own = role.own_thinking ?? "";
  const inherited = role.thinking && !role.own_thinking ? THINKING_LABEL[role.thinking] : null;
  const hint = role.thinking_configured
    ? `Set in the configuration (EXACTDOCS_AI__${name.toUpperCase()}__THINKING).`
    : THINKING_HINT;
  const warning = role.thinking_unsupported
    ? `Its model takes no thinking level, so its calls leave it out: ${role.thinking_unsupported}.`
    : undefined;
  return (
    <div className="mt-2 max-w-sm">
      <SelectField
        id={`thinking-${name}`}
        label={`${ROLE_LABEL[name]} thinking`}
        value={own}
        disabled={role.thinking_configured || save.isPending}
        hint={hint}
        error={save.isError ? explainAiError(save.error) : warning}
        onChange={(e) => save.mutate((e.target.value || null) as ThinkingLevel | null)}
      >
        <option value="">
          {inherited ? `The LLM's level (${inherited})` : "The provider's default"}
        </option>
        {THINKING_LEVELS.map((level) => (
          <option key={level} value={level}>
            {THINKING_LABEL[level]}
          </option>
        ))}
      </SelectField>
    </div>
  );
}

function ProviderCard({ provider: p }: { provider: AiProvider }) {
  const queryClient = useQueryClient();
  const check = useMutation({
    mutationFn: () => checkProvider(p.name),
    onSuccess: (result) => {
      const failed = result.checks.filter((c) => c.status !== "ok").length;
      if (failed === 0) toast.success(`${p.name}: every check passed`);
      else toast.error(`${p.name}: ${failed} of ${result.checks.length} checks failed`);
    },
    onError: (error) => toast.error(`${p.name}: ${explainAiError(error)}`),
    // A check calls the profile as it is now: show the profiles as they are now too.
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: aiProvidersQueryOptions().queryKey }),
  });
  const keyTone = p.key === "none" ? pillTone.neutral : pillTone.positive;
  return (
    <li className={cn(card, "p-4")}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
            <h3 className="font-mono text-body font-semibold [overflow-wrap:anywhere]">{p.name}</h3>
            <span className={cn(pill, pillTone.neutral)}>{p.kind}</span>
            <span className={cn(pill, keyTone)}>{keyWords(p)}</span>
          </div>
          <p className="mt-1.5 text-small text-muted-foreground">{originWords(p)}</p>
          {p.base_url && (
            <p className="mt-1 font-mono text-small [overflow-wrap:anywhere]">{p.base_url}</p>
          )}
          <p className="mt-1.5 text-body">
            {p.roles.length > 0
              ? `Used for: ${p.roles.map((r) => ROLE_LABEL[r]).join(", ")}`
              : "No instance role uses it."}
          </p>
          {p.unsupported && (
            <p className="mt-1.5 text-body font-medium text-destructive">{p.unsupported}</p>
          )}
        </div>
        <Button
          variant="outline"
          aria-label={`Check ${p.name}`}
          pending={check.isPending}
          onClick={() => !check.isPending && check.mutate()}
        >
          Check
        </Button>
      </div>
      <div role="status" aria-label={`${p.name} check`} className="mt-3 text-body empty:hidden">
        {/* The status region announces it already: no second live region inside. */}
        {check.isError && (
          <p className="font-medium text-destructive">{explainAiError(check.error)}</p>
        )}
        {check.data && (
          <ul className="row-in flex flex-col gap-1.5 border-t border-rule pt-3">
            {check.data.checks.map((c) => (
              <li key={`${c.role}-${c.model}`} className="flex items-start gap-2">
                {c.status === "ok" ? (
                  <CircleCheck
                    aria-hidden="true"
                    className="mt-0.5 size-4 shrink-0 text-positive"
                  />
                ) : (
                  <CircleAlert
                    aria-hidden="true"
                    className="mt-0.5 size-4 shrink-0 text-destructive"
                  />
                )}
                <span className="[overflow-wrap:anywhere]">
                  <span className="font-medium">
                    {c.role ? ROLE_LABEL[c.role] : "Model"} {c.model}:
                  </span>{" "}
                  {c.status === "ok" ? "OK. " : "Failed. "}
                  {checkWords(c)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

function EmbeddingSection() {
  const progress = useQuery(embeddingProgressQueryOptions());
  return (
    <Section
      id="embedding"
      title="Embedding"
      description="Every version of a library with AI on is embedded in the background. While a new model embeds, the old space keeps answering."
    >
      {progress.isPending ? (
        <CardSkeleton label="Loading the embedding progress" />
      ) : progress.isError ? (
        <Problem error={progress.error} onRetry={() => progress.refetch()} />
      ) : (
        <div className="flex flex-col gap-4">
          <p className="text-body">
            Model:{" "}
            {progress.data.model ? (
              <span className="font-mono text-small">{progress.data.model}</span>
            ) : (
              <span className="text-muted-foreground">none configured</span>
            )}
          </p>
          {progress.data.spaces.length === 0 ? (
            <EmptyState title="Nothing has been embedded yet">
              Embedding starts when a library has AI on and a model is set for the embedding role.
            </EmptyState>
          ) : (
            <ul className="flex flex-col gap-3">
              {progress.data.spaces.map((s) => (
                <SpaceRow key={s.id} space={s} />
              ))}
            </ul>
          )}
        </div>
      )}
    </Section>
  );
}

function SpaceRow({ space: s }: { space: SpaceProgress }) {
  const done = percent(s.chunks_embedded, s.chunks);
  const name = `Space ${s.id}: ${s.model}`;
  return (
    <li className={cn(card, "p-4")}>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5">
        <h3 className="font-mono text-body font-semibold [overflow-wrap:anywhere]">{name}</h3>
        <span className={cn(pill, s.state === "active" ? pillTone.positive : pillTone.route)}>
          {s.state === "active" ? "Searched" : "Building"}
        </span>
      </div>
      <p className="mt-1 text-small text-muted-foreground">
        {s.current ? "Configured model" : "Retired once the new one is done"} · {s.profile_kind} ·{" "}
        {s.dimensions} dimensions · created {absoluteTime(s.created_at)}
      </p>
      <Meter value={done} label={`${name} progress`} className="mt-3" />
      <p className="mt-2 text-body tabular-nums">
        {done}%: {count(s.chunks_embedded)} of {count(s.chunks)} chunks,{" "}
        {count(s.versions_embedded)} of {count(s.versions)} versions
      </p>
    </li>
  );
}

function UsageSection() {
  const usage = useQuery(aiUsageQueryOptions());
  return (
    <Section
      id="usage"
      title="Usage and budgets"
      description="What AI calls spent today and this month (UTC), and what is left of each budget. A used-up budget skips the paid step; searches still answer."
    >
      {usage.isPending ? (
        <div aria-busy="true" className={cn(card, "flex flex-col gap-4 p-4")}>
          <span className="sr-only">Loading the usage</span>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-5 w-full" />
          ))}
        </div>
      ) : usage.isError ? (
        <Problem error={usage.error} onRetry={() => usage.refetch()} />
      ) : (
        <>
          <p className="mb-3 text-body text-muted-foreground">
            LLM searches per minute per caller:{" "}
            {usage.data.llm_searches_per_minute ?? "not limited"}
          </p>
          {/* Scrolls sideways on a phone: focusable, so a keyboard can scroll it too. */}
          <section
            aria-label="Usage table"
            // biome-ignore lint/a11y/noNoninteractiveTabindex: a table wider than the screen scrolls
            tabIndex={0}
            className="overflow-x-auto rounded-lg border border-border outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <table className="w-full min-w-[56rem] text-left text-body">
              <thead className="bg-raised text-small text-muted-foreground">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    Scope
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    Today
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    This month
                  </th>
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    Budgets
                  </th>
                </tr>
              </thead>
              <tbody>
                {usage.data.scopes.map((s) => (
                  <UsageRow key={`${s.scope}:${s.id}`} scope={s} />
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </Section>
  );
}

function spent(s: ScopeUsage["day"]) {
  const unpriced = s.unpriced_requests ? `, ${count(s.unpriced_requests)} unpriced` : "";
  // Local models cost nothing: their tokens are shown, but no token budget counts them.
  const local = s.local_tokens ? ` (+${count(s.local_tokens)} local, not budgeted)` : "";
  return `${usd(s.usd)} · ${count(s.tokens)} tokens${local} · ${count(s.requests)} calls${unpriced}`;
}

function UsageRow({ scope: s }: { scope: ScopeUsage }) {
  return (
    <tr className="border-t border-rule align-top">
      <th scope="row" className="px-4 py-3 font-medium [overflow-wrap:anywhere]">
        {scopeName(s)}
      </th>
      <td className="px-4 py-3 text-right tabular-nums">{spent(s.day)}</td>
      <td className="px-4 py-3 text-right tabular-nums">{spent(s.month)}</td>
      <td className="min-w-64 px-4 py-3">
        {s.budgets.length === 0 ? (
          <span className="text-muted-foreground">None</span>
        ) : (
          <ul className="flex flex-col gap-3">
            {s.budgets.map((b: Budget) => (
              <BudgetItem key={b.window} budget={b} />
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}

function BudgetItem({ budget: b }: { budget: Budget }) {
  const note = ownBudgetNote(b);
  const used = budgetUsed(b);
  const tone = b.reached ? "destructive" : used >= BUDGET_NEAR ? "warning" : "route";
  return (
    <li>
      <span className={b.reached ? "font-medium text-destructive" : undefined}>
        {budgetWords(b)}
        {b.reached && ` · reached until ${absoluteTimeWithZone(b.resets_at)}`}
      </span>
      <Meter
        role="meter"
        value={used}
        tone={tone}
        label={`${b.window === "day" ? "Today's" : "This month's"} budget used`}
        className="mt-1.5"
      />
      {note && <span className="mt-1 block text-small text-muted-foreground">{note}</span>}
    </li>
  );
}
