import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CircleAlert,
  CircleCheck,
  Cpu,
  KeyRound,
  Layers,
  RefreshCw,
  Server,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import {
  type AiProvider,
  type AiRole,
  aiProvidersQueryOptions,
  aiRolesQueryOptions,
  THINKING_LEVELS,
  type ThinkingLevel,
} from "@/shared/lib/ai-queries";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { absoluteTime } from "@/shared/lib/time";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { cn } from "@/shared/lib/utils";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { StateBadge } from "@/shared/ui/data-table/cells";
import { Meter } from "@/shared/ui/meter";
import { EmptyState, Page, PageHeader, Section } from "@/shared/ui/page";
import { SelectField } from "@/shared/ui/select-field";
import { Skeleton } from "@/shared/ui/skeleton";
import { checkProvider, embeddingProgressQueryOptions, setRoleThinking } from "../api/ai";
import { messages } from "../messages";
import {
  checkWords,
  explainAiError,
  keyWords,
  originWords,
  percent,
  type SpaceProgress,
} from "../model/ai";
import { UsageSection } from "./usage-table";

const SKELETON_ROWS = [0, 1, 2, 3] as const;
const card = "rounded-lg border border-border bg-raised";

/** The instance's AI: providers and roles, embedding progress and spend (admins). */
export function AiPage() {
  const t = useMessages(messages);
  const title = usePageTitle(t.page.title);
  return (
    <Page>
      <PageHeader
        title={t.page.title}
        icon={<Cpu />}
        headingRef={title}
        description={t.page.description}
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
  const c = useMessages(common);
  const language = useLanguage();
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-lg bg-destructive-soft py-1.5 pr-1.5 pl-4"
    >
      <p className="text-body font-medium text-destructive-ink">
        {explainAiError(error, language)}
      </p>
      <Button variant="ghost" onClick={onRetry}>
        <RefreshCw aria-hidden="true" data-icon-motion="refresh" />
        {c.retry}
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
  const t = useMessages(messages);
  const providers = useQuery(aiProvidersQueryOptions());
  const roles = useQuery(aiRolesQueryOptions());
  return (
    <Section
      id="providers"
      icon={<Server />}
      title={t.providers.title}
      description={t.providers.description}
    >
      <div className="flex flex-col gap-4">
        {roles.isError ? (
          <Problem error={roles.error} onRetry={() => roles.refetch()} />
        ) : roles.data ? (
          <RoleList roles={roles.data} />
        ) : (
          <div aria-busy="true" className={cn(card, "flex flex-col gap-3 p-4")}>
            <span className="sr-only">{t.providers.loadingRoles}</span>
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-5 w-full" />
            ))}
          </div>
        )}
        {providers.isPending ? (
          <CardSkeleton label={t.providers.loading} />
        ) : providers.isError ? (
          <Problem error={providers.error} onRetry={() => providers.refetch()} />
        ) : providers.data.length === 0 ? (
          <EmptyState icon={<Sparkles aria-hidden="true" />} title={t.providers.noneTitle}>
            {t.providers.none}
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
  const t = useMessages(messages);
  return (
    <div>
      <dl
        className={cn(card, "grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-2.5 p-4 text-body")}
      >
        {roles.map((r) => (
          <div key={r.role} className="contents">
            <dt className="font-medium">{t.roles[r.role]}</dt>
            <dd className="[overflow-wrap:anywhere]">
              {r.model ? (
                <>
                  <span className="font-mono text-small">{r.model}</span>
                  {r.source === "llm" && (
                    <span className="text-muted-foreground">{t.providers.llms}</span>
                  )}
                  {!r.profile_exists && (
                    <span className="text-destructive">{t.providers.noProfile}</span>
                  )}
                </>
              ) : (
                <span className="text-muted-foreground">{t.providers.notSet}</span>
              )}
              {r.model && (r.role === "llm" || r.role === "judge") && (
                <RoleThinking role={r} name={r.role} />
              )}
            </dd>
          </div>
        ))}
      </dl>
      {roles.some((r) => !r.model) && (
        <p className="mt-2 text-small text-muted-foreground">{t.providers.notSetHint}</p>
      )}
    </div>
  );
}

/** The thinking level of the `llm` or `judge` role: set here, unless the configuration sets it. */
function RoleThinking({ role, name }: { role: AiRole; name: "llm" | "judge" }) {
  const t = useMessages(messages);
  const language = useLanguage();
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (thinking: ThinkingLevel | null) => setRoleThinking(name, thinking),
    onSuccess: (_, thinking) => {
      toast.success(
        thinking ? t.thinking.set(name, t.thinkingLevels[thinking]) : t.thinking.reset(name),
      );
      return queryClient.invalidateQueries({ queryKey: aiRolesQueryOptions().queryKey });
    },
  });
  const own = role.own_thinking ?? "";
  const inherited = role.thinking && !role.own_thinking ? t.thinkingLevels[role.thinking] : null;
  const hint = role.thinking_configured ? t.thinking.configured(name) : t.thinking.hint;
  const warning = role.thinking_unsupported
    ? t.thinking.unsupported(role.thinking_unsupported)
    : undefined;
  return (
    <div className="mt-2 max-w-sm">
      <SelectField
        id={`thinking-${name}`}
        label={t.thinking.label[name]}
        value={own}
        disabled={role.thinking_configured || save.isPending}
        hint={hint}
        error={save.isError ? explainAiError(save.error, language) : warning}
        onChange={(e) => save.mutate((e.target.value || null) as ThinkingLevel | null)}
      >
        <option value="">
          {inherited ? t.thinking.inherited(inherited) : t.thinking.providerDefault}
        </option>
        {THINKING_LEVELS.map((level) => (
          <option key={level} value={level}>
            {t.thinkingLevels[level]}
          </option>
        ))}
      </SelectField>
    </div>
  );
}

function ProviderCard({ provider: p }: { provider: AiProvider }) {
  const t = useMessages(messages);
  const language = useLanguage();
  const queryClient = useQueryClient();
  const check = useMutation({
    mutationFn: () => checkProvider(p.name),
    onSuccess: (result) => {
      const failed = result.checks.filter((c) => c.status !== "ok").length;
      if (failed === 0) toast.success(t.providers.allPassed(p.name));
      else toast.error(t.providers.someFailed(p.name, failed, result.checks.length));
    },
    onError: (error) => toast.error(`${p.name}: ${explainAiError(error, language)}`),
    // A check calls the profile as it is now: show the profiles as they are now too.
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: aiProvidersQueryOptions().queryKey }),
  });
  return (
    <li className={cn(card, "p-4")}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
            <h3 className="font-mono text-body font-semibold [overflow-wrap:anywhere]">{p.name}</h3>
            <Badge>{p.kind}</Badge>
            <Badge tone={p.key === "none" ? "neutral" : "positive"}>
              <KeyRound aria-hidden="true" className="size-3" />
              {keyWords(p, language)}
            </Badge>
          </div>
          <p className="mt-1.5 text-small text-muted-foreground">{originWords(p, language)}</p>
          {p.base_url && (
            <p className="mt-1 font-mono text-small [overflow-wrap:anywhere]">{p.base_url}</p>
          )}
          <p className="mt-1.5 text-body">
            {p.roles.length > 0
              ? t.providers.usedFor(p.roles.map((r) => t.roles[r]).join(", "))
              : t.providers.unused}
          </p>
          {p.unsupported && (
            <p className="mt-1.5 text-body font-medium text-destructive">{p.unsupported}</p>
          )}
        </div>
        <Button
          variant="outline"
          aria-label={t.providers.checkLabel(p.name)}
          pending={check.isPending}
          onClick={() => !check.isPending && check.mutate()}
        >
          <CircleCheck aria-hidden="true" data-icon-motion="pop" />
          {t.providers.check}
        </Button>
      </div>
      <div
        role="status"
        aria-label={t.providers.checkStatus(p.name)}
        className="mt-3 text-body empty:hidden"
      >
        {/* The status region announces it already: no second live region inside. */}
        {check.isError && (
          <p className="font-medium text-destructive">{explainAiError(check.error, language)}</p>
        )}
        {check.data && (
          <ul className="row-in flex flex-col gap-1.5 border-t border-rule pt-3">
            {check.data.checks.map((c) => (
              <li key={`${c.role}-${c.model}`} className="flex items-start gap-2">
                {c.status === "ok" ? (
                  <CircleCheck
                    aria-hidden="true"
                    data-icon-motion="draw"
                    className="mt-0.5 size-4 shrink-0 text-positive"
                  />
                ) : (
                  <CircleAlert
                    aria-hidden="true"
                    data-icon-motion="alert"
                    className="mt-0.5 size-4 shrink-0 text-destructive"
                  />
                )}
                <span className="[overflow-wrap:anywhere]">
                  <span className="font-medium">
                    {c.role ? t.roles[c.role] : t.providers.model} {c.model}:
                  </span>{" "}
                  {c.status === "ok" ? t.providers.ok : t.providers.failed}
                  {checkWords(c, language)}
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
  const t = useMessages(messages);
  const progress = useQuery(embeddingProgressQueryOptions());
  return (
    <Section
      id="embedding"
      icon={<Layers />}
      title={t.embedding.title}
      description={t.embedding.description}
    >
      {progress.isPending ? (
        <CardSkeleton label={t.embedding.loading} />
      ) : progress.isError ? (
        <Problem error={progress.error} onRetry={() => progress.refetch()} />
      ) : (
        <div className="flex flex-col gap-4">
          <p className="text-body">
            {t.embedding.model}{" "}
            {progress.data.model ? (
              <span className="font-mono text-small">{progress.data.model}</span>
            ) : (
              <span className="text-muted-foreground">{t.embedding.noModel}</span>
            )}
          </p>
          {progress.data.spaces.length === 0 ? (
            <EmptyState title={t.embedding.emptyTitle}>{t.embedding.empty}</EmptyState>
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
  const t = useMessages(messages);
  const language = useLanguage();
  const done = percent(s.chunks_embedded, s.chunks);
  const name = t.embedding.space(s.id, s.model);
  return (
    <li className={cn(card, "p-4")}>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5">
        <h3 className="font-mono text-body font-semibold [overflow-wrap:anywhere]">{name}</h3>
        {s.state === "active" ? (
          <StateBadge state="succeeded" label={t.embedding.searched} />
        ) : (
          <StateBadge state="running" label={t.embedding.building} />
        )}
      </div>
      <p className="mt-1 text-small text-muted-foreground">
        {s.current ? t.embedding.current : t.embedding.retiring} · {s.profile_kind} ·{" "}
        {t.embedding.dimensions(s.dimensions)} ·{" "}
        {t.embedding.created(absoluteTime(s.created_at, language))}
      </p>
      <Meter value={done} label={t.embedding.progressLabel(name)} className="mt-3" />
      <p className="mt-2 text-body tabular-nums">
        {t.embedding.progress(done, s.chunks_embedded, s.chunks, s.versions_embedded, s.versions)}
      </p>
    </li>
  );
}
