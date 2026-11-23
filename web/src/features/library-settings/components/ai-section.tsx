import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, RefreshCw, ShieldOff } from "lucide-react";
import { type FormEvent, Fragment, useState } from "react";
import { toast } from "sonner";
import {
  type AiProvider,
  type AiRole,
  aiLabels,
  aiProvidersQueryOptions,
  aiRolesQueryOptions,
  THINKING_LEVELS,
  type ThinkingLevel,
} from "@/shared/lib/ai-queries";
import { useLanguage } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { pill, pillTone } from "@/shared/ui/recipes";
import { SelectField } from "@/shared/ui/select-field";
import { Skeleton } from "@/shared/ui/skeleton";
import { libraryRetrievalQueryOptions, saveLibraryRetrieval } from "../api/retrieval";
import { pageMessages } from "../messages/page";
import { retrievalMessages } from "../messages/retrieval";
import { sharedMessages } from "../messages/shared";
import {
  bodyOf,
  ceilingHint,
  type DraftErrors,
  instanceThinking,
  type LibraryRetrieval,
  MAX_RERANK_TOP_N,
  modeOptions,
  modeSource,
  OVERRIDABLE,
  type OverridableRole,
  pipelineSteps,
  profileOptions,
  REPO_GUIDANCE,
  RERANK_WITH,
  type RepoGuidance,
  type RerankWith,
  type RetrievalDraft,
  retrievalDraftOf,
  rolesInUse,
  sameDraft,
  THINKING_ROLES,
  validateRetrieval,
} from "../model/retrieval";
import {
  type Activity,
  explainProfilesError,
  explainRetrievalSave,
  type Problem,
} from "../model/settings";
import { useReportDirty } from "./dirty";
import { SaveRow } from "./save-row";
import { SettingsSection } from "./settings-section";

interface Props {
  owner: string;
  repo: string;
  activity: Activity;
  onStart: () => void;
}

/** Which pipeline answers for the library, and the settings that choose it (admins). */
export function AiSection({ owner, repo, activity, onStart }: Props) {
  const language = useLanguage();
  const t = retrievalMessages[language];
  const retrieval = useQuery(libraryRetrievalQueryOptions(owner, repo));
  const providers = useQuery(aiProvidersQueryOptions());
  const roles = useQuery(aiRolesQueryOptions());
  return (
    <SettingsSection id="ai" title={pageMessages[language].sections.ai} description={t.description}>
      {retrieval.isPending ? (
        <div role="status" aria-label={t.loading} className="flex flex-col gap-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-11 w-full" />
        </div>
      ) : retrieval.isError ? (
        <div>
          <FormAlert
            id="ai-load-alert"
            message={explainRetrievalSave(retrieval.error, language).message}
          />
          <Button
            type="button"
            variant="outline"
            aria-busy={retrieval.isFetching}
            onClick={() => retrieval.refetch()}
          >
            <RefreshCw aria-hidden="true" data-icon-motion="refresh" />
            {sharedMessages[language].retry}
          </Button>
        </div>
      ) : (
        <>
          <PipelineSummary r={retrieval.data} roles={roles.data} />
          <AiForm
            owner={owner}
            repo={repo}
            r={retrieval.data}
            roles={roles.data}
            providers={providers.data}
            providersError={
              providers.isError ? explainProfilesError(providers.error, language) : undefined
            }
            activity={activity}
            onStart={onStart}
          />
        </>
      )}
    </SettingsSection>
  );
}

/** Anything set beyond the instance's defaults: the advanced controls start open then. */
function isCustomised(d: RetrievalDraft): boolean {
  return Boolean(
    d.llm.profile ||
      d.judge.profile ||
      d.reranker.profile ||
      d.rerankTopN ||
      d.rerankWith ||
      d.dailyUsd ||
      d.monthlyUsd ||
      d.dailyTokens ||
      d.monthlyTokens,
  );
}

/** The pipeline a search without `mode` runs now, step by step, and the models it uses. */
function PipelineSummary({
  r,
  roles,
}: {
  r: LibraryRetrieval;
  roles: readonly AiRole[] | undefined;
}) {
  const language = useLanguage();
  const t = retrievalMessages[language];
  const ai = aiLabels[language];
  const used = rolesInUse(r, roles);
  return (
    <section aria-labelledby="pipeline-heading" className="mb-6 rounded-lg bg-raised p-4">
      <h3 id="pipeline-heading" className="text-body font-medium text-muted-foreground">
        {t.effectivePipeline}
      </h3>
      <p className="mt-0.5 text-section font-semibold" data-testid="effective-mode">
        {t.modes[r.effective_mode]}
      </p>
      <p className="mt-0.5 text-body text-muted-foreground">{modeSource(r, language)}</p>
      <ol className="mt-3 flex flex-wrap gap-x-2 gap-y-1 text-body [&>li:not(:last-child)]:after:ml-2 [&>li:not(:last-child)]:after:text-muted-foreground [&>li:not(:last-child)]:after:content-['→']">
        {pipelineSteps(r, language).map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      {r.ai_enabled ? (
        used.length > 0 && (
          <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-body">
            {used.map((u) => (
              <div key={u.role} className="contents">
                <dt className="text-muted-foreground">{ai.roles[u.role]}</dt>
                <dd className="[overflow-wrap:anywhere]">
                  <span className="font-mono">{u.model ?? t.configured}</span>
                  <span className="text-muted-foreground">
                    {u.from === "library" ? t.fromLibrary : t.fromInstance}
                  </span>
                </dd>
              </div>
            ))}
          </dl>
        )
      ) : (
        <p className="mt-3 flex items-start gap-2 text-body">
          <ShieldOff aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-route" />
          <span>{t.noContentSent}</span>
        </p>
      )}
    </section>
  );
}

interface FormProps {
  owner: string;
  repo: string;
  r: LibraryRetrieval;
  /** The instance's roles, for the level a library without its own uses; undefined until read. */
  roles: readonly AiRole[] | undefined;
  /** Undefined while the profiles load or when they could not be read. */
  providers: readonly AiProvider[] | undefined;
  /** Why the profiles could not be read, if they could not. */
  providersError: string | undefined;
  activity: Activity;
  onStart: () => void;
}

function AiForm({
  owner,
  repo,
  r,
  roles,
  providers,
  providersError,
  activity,
  onStart,
}: FormProps) {
  const language = useLanguage();
  const t = retrievalMessages[language];
  const ai = aiLabels[language];
  const queryClient = useQueryClient();
  const saved = retrievalDraftOf(r);
  const [draft, setDraft] = useState<RetrievalDraft>(saved);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [problem, setProblem] = useState<Problem>();
  const [done, setDone] = useState(false);
  const unchanged = sameDraft(saved, draft);
  useReportDirty("ai", !unchanged);

  const save = useMutation({
    mutationFn: () => saveLibraryRetrieval(owner, repo, bodyOf(draft)),
    onSuccess: (data) => {
      // The fields show what was stored: the server may have normalised it.
      setDraft(retrievalDraftOf(data));
      setDone(true);
      toast.success(t.savedToast);
      setProblem(undefined);
      queryClient.setQueryData(libraryRetrievalQueryOptions(owner, repo).queryKey, data);
    },
    onError: (error) => {
      const p = explainRetrievalSave(error, language);
      if (p.field === "mode") {
        setErrors({ mode: p.message });
        document.getElementById("ai-mode")?.focus();
      } else {
        setProblem(p);
      }
    },
  });

  function edit(patch: Partial<RetrievalDraft>) {
    setDraft((d) => ({ ...d, ...patch }));
    setDone(false);
    setErrors((e) => {
      const next = { ...e };
      for (const key of Object.keys(patch)) delete next[key as keyof DraftErrors];
      return next;
    });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (save.isPending || unchanged) return;
    const found = validateRetrieval(draft, r.budget_ceilings, r.budgets, language);
    setErrors(found);
    setProblem(undefined);
    const first = Object.keys(found)[0];
    if (first) {
      document.getElementById(`ai-${first}`)?.focus();
      return;
    }
    onStart();
    save.mutate();
  }

  const off = !draft.aiEnabled;
  const customised = isCustomised(saved);
  const [advanced, setAdvanced] = useState(customised);
  const failedAdvanced = Object.keys(errors).some((k) => k !== "mode");
  return (
    <form onSubmit={submit} noValidate>
      <FormAlert id="ai-alert" message={problem?.message} link={problem?.link} />
      <div className="flex flex-col gap-5">
        <label className="inline-flex min-h-11 cursor-pointer items-center gap-2.5 self-start text-body font-medium md:min-h-8">
          <input
            id="ai-aiEnabled"
            type="checkbox"
            checked={draft.aiEnabled}
            onChange={(e) =>
              // Off leaves BM25 only, so a mode that needs a model goes with it.
              edit(
                e.target.checked
                  ? { aiEnabled: true }
                  : { aiEnabled: false, mode: draft.mode === "bm25" ? "bm25" : "" },
              )
            }
            className="size-4 cursor-pointer accent-primary"
          />
          {t.useAi}
        </label>
        {off && <p className="fade-in -mt-3 text-body text-muted-foreground">{t.offNote}</p>}
        <SelectField
          id="ai-mode"
          label={t.mode}
          value={draft.mode}
          error={errors.mode}
          hint={t.modeHint}
          onChange={(e) => edit({ mode: e.target.value })}
        >
          <option value="">
            {r.instance_mode ? t.instanceDefault(t.modes[r.instance_mode]) : t.bestAvailable}
          </option>
          {modeOptions(r, draft, language).map((o) => (
            <option key={o.value} value={o.value} disabled={o.disabled}>
              {o.label}
            </option>
          ))}
        </SelectField>
        <details
          open={advanced || failedAdvanced}
          onToggle={(e) => setAdvanced(e.currentTarget.open)}
          className="group rounded-lg border border-border"
        >
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-lg px-4 text-body font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
            <ChevronRight
              aria-hidden="true"
              className="size-4 text-muted-foreground transition-transform duration-(--dur) ease-(--ease-out) group-open:rotate-90 motion-reduce:transition-none"
            />
            {t.advanced}
            {customised && (
              <span className={cn(pill, pillTone.route, "ml-auto")}>{t.customised}</span>
            )}
          </summary>
          <div className="flex flex-col gap-5 border-t border-rule p-4">
            {/* A legend is no flex item: the fieldset stays a block and the fields get their own box. */}
            <fieldset disabled={off} className="disabled:opacity-60">
              <legend className="mb-1 text-body font-medium">{t.models}</legend>
              <p className="text-body text-muted-foreground">{t.modelsNote}</p>
              <div className="mt-5 flex flex-col gap-5">
                {providersError ? (
                  <p role="alert" className="text-body font-medium text-destructive">
                    {providersError}
                  </p>
                ) : providers === undefined ? (
                  <p className="text-body text-muted-foreground">{t.loadingProfiles}</p>
                ) : null}
                {OVERRIDABLE.map((role) => {
                  const thinking = THINKING_ROLES.find(([r]) => r === role);
                  return (
                    <Fragment key={role}>
                      <RoleOverride
                        role={role}
                        draft={draft}
                        providers={providers}
                        error={errors[role]}
                        onChange={(value) => edit({ [role]: value })}
                      />
                      {thinking && (
                        <SelectField
                          id={`ai-${thinking[1]}`}
                          label={t.thinking(ai.roles[thinking[0]])}
                          value={draft[thinking[1]]}
                          hint={ai.thinkingHint}
                          onChange={(e) =>
                            edit({ [thinking[1]]: e.target.value as "" | ThinkingLevel })
                          }
                        >
                          <option value="">
                            {instanceThinking(thinking[0], roles, (l) => ai.thinking[l], language)}
                          </option>
                          {THINKING_LEVELS.map((level) => (
                            <option key={level} value={level}>
                              {ai.thinking[level]}
                            </option>
                          ))}
                        </SelectField>
                      )}
                    </Fragment>
                  );
                })}
                <Field
                  id="ai-rerankTopN"
                  label={t.rerankTopN}
                  inputMode="numeric"
                  value={draft.rerankTopN}
                  placeholder={String(r.effective_rerank_top_n)}
                  error={errors.rerankTopN}
                  hint={t.rerankTopNHint(MAX_RERANK_TOP_N)}
                  onChange={(e) => edit({ rerankTopN: e.target.value })}
                />
                <SelectField
                  id="ai-rerankWith"
                  label={t.rerankWith}
                  value={draft.rerankWith}
                  hint={t.rerankWithHint}
                  onChange={(e) => edit({ rerankWith: e.target.value as "" | RerankWith })}
                >
                  <option value="">
                    {t.instanceChoice(t.rerankWithLabel[r.instance_rerank_with])}
                  </option>
                  {RERANK_WITH.map((value) => (
                    <option key={value} value={value}>
                      {t.rerankWithLabel[value]}
                    </option>
                  ))}
                </SelectField>
              </div>
            </fieldset>
            <SelectField
              id="ai-repoGuidance"
              label={t.repoGuidance}
              value={draft.repoGuidance}
              disabled={off}
              hint={t.guidanceHint(t.guidance[draft.repoGuidance]?.hint ?? "")}
              onChange={(e) => edit({ repoGuidance: e.target.value as RepoGuidance })}
            >
              {REPO_GUIDANCE.map((g) => (
                <option key={g} value={g}>
                  {t.guidance[g].label}
                </option>
              ))}
            </SelectField>
            <fieldset>
              <legend className="mb-1 text-body font-medium">{t.spendLimits}</legend>
              <p className="text-body text-muted-foreground">{t.spendNote}</p>
              <div className="mt-5 grid gap-5 sm:grid-cols-2">
                <Field
                  id="ai-dailyUsd"
                  label={t.dailyUsd}
                  inputMode="decimal"
                  value={draft.dailyUsd}
                  error={errors.dailyUsd}
                  hint={ceilingHint(r.budget_ceilings, "daily_usd", "USD", r.budgets, language)}
                  onChange={(e) => edit({ dailyUsd: e.target.value })}
                />
                <Field
                  id="ai-monthlyUsd"
                  label={t.monthlyUsd}
                  inputMode="decimal"
                  value={draft.monthlyUsd}
                  error={errors.monthlyUsd}
                  hint={ceilingHint(r.budget_ceilings, "monthly_usd", "USD", r.budgets, language)}
                  onChange={(e) => edit({ monthlyUsd: e.target.value })}
                />
                <Field
                  id="ai-dailyTokens"
                  label={t.dailyTokens}
                  inputMode="numeric"
                  value={draft.dailyTokens}
                  error={errors.dailyTokens}
                  hint={ceilingHint(
                    r.budget_ceilings,
                    "daily_tokens",
                    "tokens",
                    r.budgets,
                    language,
                  )}
                  onChange={(e) => edit({ dailyTokens: e.target.value })}
                />
                <Field
                  id="ai-monthlyTokens"
                  label={t.monthlyTokens}
                  inputMode="numeric"
                  value={draft.monthlyTokens}
                  error={errors.monthlyTokens}
                  hint={ceilingHint(
                    r.budget_ceilings,
                    "monthly_tokens",
                    "tokens",
                    r.budgets,
                    language,
                  )}
                  onChange={(e) => edit({ monthlyTokens: e.target.value })}
                />
              </div>
            </fieldset>
          </div>
        </details>
        <SaveRow
          label={t.save}
          pending={save.isPending}
          blocked={save.isPending || unchanged}
          saved={done && unchanged && activity.by === "ai"}
        />
      </div>
    </form>
  );
}

function RoleOverride({
  role,
  draft,
  providers,
  error,
  onChange,
}: {
  role: OverridableRole;
  draft: RetrievalDraft;
  providers: readonly AiProvider[] | undefined;
  error: string | undefined;
  onChange: (value: RetrievalDraft[OverridableRole]) => void;
}) {
  const language = useLanguage();
  const t = retrievalMessages[language];
  const value = draft[role];
  const label = aiLabels[language].roles[role];
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <SelectField
        id={`ai-${role}-profile`}
        label={t.profile(label)}
        value={value.profile}
        // Until the profiles are read only the stored one is offered, never marked missing.
        disabled={providers === undefined}
        onChange={(e) => onChange({ profile: e.target.value, model: value.model })}
      >
        <option value="">{role === "judge" ? t.instanceProfileJudge : t.instanceProfile}</option>
        {profileOptions(providers, value.profile, language).map((p) => (
          <option key={p.value} value={p.value}>
            {p.value}
            {p.note}
          </option>
        ))}
      </SelectField>
      {value.profile ? (
        <Field
          id={`ai-${role}`}
          label={t.model(label)}
          autoComplete="off"
          value={value.model}
          error={error}
          onChange={(e) => onChange({ profile: value.profile, model: e.target.value })}
        />
      ) : null}
    </div>
  );
}
