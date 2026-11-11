import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck } from "lucide-react";
import type { ReactNode } from "react";
import {
  type AiProvider,
  type AiRole,
  aiProvidersQueryOptions,
  aiRolesQueryOptions,
  ROLE_LABEL,
} from "@/shared/lib/ai-queries";
import { absoluteTime, absoluteTimeWithZone } from "@/shared/lib/time";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Button } from "@/shared/ui/button";
import { aiUsageQueryOptions, checkProvider, embeddingProgressQueryOptions } from "../api/ai";
import {
  type Budget,
  budgetWords,
  checkWords,
  count,
  explainAiError,
  keyWords,
  originWords,
  percent,
  type ScopeUsage,
  type SpaceProgress,
  scopeName,
  usd,
} from "../model/ai";

const heading = "font-serif text-2xl font-semibold tracking-tight";

/** The instance's AI: providers and roles, embedding progress and spend (admins). */
export function AiPage() {
  const title = usePageTitle("AI");
  return (
    <main className="px-4 py-6 pb-12 sm:px-6 sm:py-8 sm:pb-16 2xl:mx-auto 2xl:max-w-[72rem]">
      <h1
        ref={title}
        tabIndex={-1}
        className="font-serif text-4xl font-semibold tracking-tight outline-none"
      >
        AI
      </h1>
      <p className="mt-1 max-w-prose text-muted-foreground">
        The providers and models this instance uses, how far embedding has got, and what AI calls
        spent. Keys are never shown.
      </p>
      <ProvidersSection />
      <EmbeddingSection />
      <UsageSection />
    </main>
  );
}

function Section({
  id,
  title,
  intro,
  children,
}: {
  id: string;
  title: string;
  intro: string;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="mt-12 border-t border-border pt-10">
      <h2 id={id} className={heading}>
        {title}
      </h2>
      <p className="mt-1.5 max-w-prose text-muted-foreground">{intro}</p>
      <div className="mt-6">{children}</div>
    </section>
  );
}

function Problem({ error }: { error: unknown }) {
  return (
    <p role="alert" className="text-sm font-medium text-destructive">
      {explainAiError(error)}
    </p>
  );
}

function ProvidersSection() {
  const providers = useQuery(aiProvidersQueryOptions());
  const roles = useQuery(aiRolesQueryOptions());
  return (
    <Section
      id="providers-heading"
      title="Providers and roles"
      intro="Each role is a model of a provider profile. Check a profile to make one small call per role that uses it."
    >
      {roles.isError ? (
        <Problem error={roles.error} />
      ) : (
        roles.data && <RoleList roles={roles.data} />
      )}
      {providers.isPending ? (
        <p className="mt-6 text-sm text-muted-foreground">Loading the providers…</p>
      ) : providers.isError ? (
        <Problem error={providers.error} />
      ) : providers.data.length === 0 ? (
        <p className="mt-6 text-sm text-muted-foreground">
          No provider is configured: searches use BM25 and nothing leaves the instance.
        </p>
      ) : (
        <ul className="mt-6 flex flex-col gap-4">
          {providers.data.map((p) => (
            <ProviderCard key={p.name} provider={p} />
          ))}
        </ul>
      )}
    </Section>
  );
}

function RoleList({ roles }: { roles: readonly AiRole[] }) {
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-2 text-sm">
      {roles.map((r) => (
        <div key={r.role} className="contents">
          <dt className="font-medium">{ROLE_LABEL[r.role]}</dt>
          <dd className="[overflow-wrap:anywhere]">
            {r.model ? (
              <>
                <span className="font-mono">{r.model}</span>
                {r.source === "llm" && <span className="text-muted-foreground"> (the LLM's)</span>}
                {!r.profile_exists && (
                  <span className="text-destructive"> (its profile does not exist)</span>
                )}
              </>
            ) : (
              <span className="text-muted-foreground">Not set</span>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function ProviderCard({ provider: p }: { provider: AiProvider }) {
  const queryClient = useQueryClient();
  const check = useMutation({
    mutationFn: () => checkProvider(p.name),
    // A check calls the profile as it is now: show the profiles as they are now too.
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: aiProvidersQueryOptions().queryKey }),
  });
  const label = `Check ${p.name}`;
  return (
    <li className="rounded-lg bg-secondary/60 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h3 className="font-mono text-base font-semibold [overflow-wrap:anywhere]">{p.name}</h3>
          <p className="text-sm text-muted-foreground">
            {p.kind} · {originWords(p)} · {keyWords(p)}
          </p>
          {p.base_url && <p className="font-mono text-sm [overflow-wrap:anywhere]">{p.base_url}</p>}
          <p className="mt-1 text-sm">
            {p.roles.length > 0
              ? `Used for: ${p.roles.map((r) => ROLE_LABEL[r]).join(", ")}`
              : "No instance role uses it."}
          </p>
          {p.unsupported && (
            <p className="mt-1 text-sm font-medium text-destructive">{p.unsupported}</p>
          )}
        </div>
        <Button
          type="button"
          aria-label={label}
          aria-disabled={check.isPending}
          aria-busy={check.isPending}
          className="bg-secondary text-foreground ring-1 ring-inset ring-border hover:bg-accent"
          onClick={() => !check.isPending && check.mutate()}
        >
          {check.isPending ? "Checking" : "Check"}
        </Button>
      </div>
      <div role="status" aria-label={`${p.name} check`} className="mt-2 text-sm">
        {/* The status region announces it already: no second live region inside. */}
        {check.isError && (
          <p className="font-medium text-destructive">{explainAiError(check.error)}</p>
        )}
        {check.data && (
          <ul className="flex flex-col gap-1">
            {check.data.checks.map((c) => (
              <li key={`${c.role}-${c.model}`} className="flex items-start gap-2">
                {c.status === "ok" ? (
                  <CircleCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-mark" />
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
      id="embedding-heading"
      title="Embedding"
      intro="Every version of a library with AI on is embedded in the background. While a new model embeds, the old space keeps answering."
    >
      {progress.isPending ? (
        <p className="text-sm text-muted-foreground">Loading the embedding progress…</p>
      ) : progress.isError ? (
        <Problem error={progress.error} />
      ) : (
        <>
          <p className="text-sm">
            Model:{" "}
            {progress.data.model ? (
              <span className="font-mono">{progress.data.model}</span>
            ) : (
              <span className="text-muted-foreground">none configured</span>
            )}
          </p>
          {progress.data.spaces.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">Nothing has been embedded yet.</p>
          ) : (
            <ul className="mt-4 flex flex-col gap-4">
              {progress.data.spaces.map((s) => (
                <SpaceRow key={s.id} space={s} />
              ))}
            </ul>
          )}
        </>
      )}
    </Section>
  );
}

function SpaceRow({ space: s }: { space: SpaceProgress }) {
  const done = percent(s.chunks_embedded, s.chunks);
  const name = `Space ${s.id}: ${s.model}`;
  return (
    <li className="rounded-lg bg-secondary/60 p-4 sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4">
        <h3 className="font-mono text-base font-semibold [overflow-wrap:anywhere]">{name}</h3>
        <p className="text-sm text-muted-foreground">
          {s.state === "active" ? "Searched" : "Building"}
          {s.current ? " · configured model" : " · retired once the new one is done"}
        </p>
      </div>
      <p className="text-sm text-muted-foreground">
        {s.profile_kind} · {s.dimensions} dimensions · created {absoluteTime(s.created_at)}
      </p>
      <progress
        className="mt-3 h-2 w-full overflow-hidden rounded-full accent-primary"
        max={100}
        value={done}
        aria-label={`${name} progress`}
      />
      <p className="mt-1 text-sm">
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
      id="usage-heading"
      title="Usage and budgets"
      intro="What AI calls spent today and this month (UTC), and what is left of each budget, for the instance, embedding runs, every library and account that spent something, and every library with budgets of its own. A used-up budget skips the paid step; searches still answer."
    >
      {usage.isPending ? (
        <p className="text-sm text-muted-foreground">Loading the usage…</p>
      ) : usage.isError ? (
        <Problem error={usage.error} />
      ) : (
        <>
          <p className="text-sm">
            LLM searches per minute per caller:{" "}
            {usage.data.llm_searches_per_minute ?? "not limited"}
          </p>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[36rem] text-left text-sm">
              <thead className="text-muted-foreground">
                <tr>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Scope
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Today
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    This month
                  </th>
                  <th scope="col" className="py-2 font-medium">
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
          </div>
        </>
      )}
    </Section>
  );
}

function spent(s: ScopeUsage["day"]) {
  const unpriced = s.unpriced_requests ? `, ${count(s.unpriced_requests)} unpriced` : "";
  return `${usd(s.usd)} · ${count(s.tokens)} tokens · ${count(s.requests)} calls${unpriced}`;
}

function UsageRow({ scope: s }: { scope: ScopeUsage }) {
  return (
    <tr className="border-t border-border align-top">
      <th scope="row" className="py-2 pr-4 font-medium [overflow-wrap:anywhere]">
        {scopeName(s)}
      </th>
      <td className="py-2 pr-4">{spent(s.day)}</td>
      <td className="py-2 pr-4">{spent(s.month)}</td>
      <td className="py-2">
        {s.budgets.length === 0 ? (
          <span className="text-muted-foreground">None</span>
        ) : (
          <ul>
            {s.budgets.map((b: Budget) => (
              <li key={b.window} className={b.reached ? "font-medium text-destructive" : undefined}>
                {budgetWords(b)}
                {b.reached && ` · reached until ${absoluteTimeWithZone(b.resets_at)}`}
              </li>
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}
