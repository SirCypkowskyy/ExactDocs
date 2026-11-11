import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldOff } from "lucide-react";
import { type FormEvent, useState } from "react";
import {
  type AiProvider,
  type AiRole,
  aiProvidersQueryOptions,
  aiRolesQueryOptions,
  ROLE_LABEL,
} from "@/shared/lib/ai-queries";
import { Button } from "@/shared/ui/button";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { SelectField } from "@/shared/ui/select-field";
import { libraryRetrievalQueryOptions, saveLibraryRetrieval } from "../api/retrieval";
import {
  bodyOf,
  ceilingHint,
  type DraftErrors,
  type LibraryRetrieval,
  MAX_RERANK_TOP_N,
  MODE_LABEL,
  modeOptions,
  modeSource,
  OVERRIDABLE,
  type OverridableRole,
  pipelineSteps,
  profileOptions,
  REPO_GUIDANCE,
  type RepoGuidance,
  type RetrievalDraft,
  retrievalDraftOf,
  rolesInUse,
  sameDraft,
  validateRetrieval,
} from "../model/retrieval";
import {
  type Activity,
  explainProfilesError,
  explainRetrievalSave,
  type Problem,
} from "../model/settings";
import { sectionHeading } from "./styles";

interface Props {
  owner: string;
  repo: string;
  activity: Activity;
  onStart: () => void;
}

/** Which pipeline answers for the library, and the settings that choose it (admins). */
export function AiSection({ owner, repo, activity, onStart }: Props) {
  const retrieval = useQuery(libraryRetrievalQueryOptions(owner, repo));
  const providers = useQuery(aiProvidersQueryOptions());
  const roles = useQuery(aiRolesQueryOptions());
  return (
    <section aria-labelledby="ai-heading" className="mt-12 border-t border-border pt-10">
      <div className="max-w-prose">
        <h2 id="ai-heading" className={sectionHeading}>
          Retrieval and AI
        </h2>
        <p className="mt-1.5 text-muted-foreground">
          How searches of this library find their answers, which models they may use, and how much
          they may spend.
        </p>
      </div>
      {retrieval.isPending ? (
        <p className="mt-4 text-sm text-muted-foreground">Loading the retrieval settings…</p>
      ) : retrieval.isError ? (
        <div className="mt-4">
          <FormAlert id="ai-load-alert" message={explainRetrievalSave(retrieval.error).message} />
        </div>
      ) : (
        <>
          <PipelineSummary r={retrieval.data} roles={roles.data} />
          <AiForm
            owner={owner}
            repo={repo}
            r={retrieval.data}
            providers={providers.data}
            providersError={providers.isError ? explainProfilesError(providers.error) : undefined}
            activity={activity}
            onStart={onStart}
          />
        </>
      )}
    </section>
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
  const used = rolesInUse(r, roles);
  return (
    <section
      aria-labelledby="pipeline-heading"
      className="mt-6 rounded-lg bg-secondary/60 p-4 sm:p-5"
    >
      <h3 id="pipeline-heading" className="text-sm font-medium text-muted-foreground">
        Effective pipeline
      </h3>
      <p className="mt-1 font-serif text-xl font-semibold" data-testid="effective-mode">
        {MODE_LABEL[r.effective_mode]}
      </p>
      <p className="mt-0.5 text-sm text-muted-foreground">{modeSource(r)}</p>
      <ol className="mt-3 list-decimal space-y-0.5 pl-5 text-sm">
        {pipelineSteps(r).map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      {r.ai_enabled ? (
        used.length > 0 && (
          <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
            {used.map((u) => (
              <div key={u.role} className="contents">
                <dt className="text-muted-foreground">{ROLE_LABEL[u.role]}</dt>
                <dd className="[overflow-wrap:anywhere]">
                  <span className="font-mono">{u.model ?? "configured"}</span>
                  <span className="text-muted-foreground">
                    {u.from === "library" ? " (this library)" : " (instance)"}
                  </span>
                </dd>
              </div>
            ))}
          </dl>
        )
      ) : (
        <p className="mt-3 flex items-start gap-2 text-sm">
          <ShieldOff aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-mark" />
          <span>No content of this library is sent to any AI provider.</span>
        </p>
      )}
    </section>
  );
}

interface FormProps {
  owner: string;
  repo: string;
  r: LibraryRetrieval;
  /** Undefined while the profiles load or when they could not be read. */
  providers: readonly AiProvider[] | undefined;
  /** Why the profiles could not be read, if they could not. */
  providersError: string | undefined;
  activity: Activity;
  onStart: () => void;
}

function AiForm({ owner, repo, r, providers, providersError, activity, onStart }: FormProps) {
  const queryClient = useQueryClient();
  const saved = retrievalDraftOf(r);
  const [draft, setDraft] = useState<RetrievalDraft>(saved);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [problem, setProblem] = useState<Problem>();
  const [done, setDone] = useState(false);
  const unchanged = sameDraft(saved, draft);

  const save = useMutation({
    mutationFn: () => saveLibraryRetrieval(owner, repo, bodyOf(draft)),
    onSuccess: (data) => {
      // The fields show what was stored: the server may have normalised it.
      setDraft(retrievalDraftOf(data));
      setDone(true);
      setProblem(undefined);
      queryClient.setQueryData(libraryRetrievalQueryOptions(owner, repo).queryKey, data);
    },
    onError: (error) => {
      const p = explainRetrievalSave(error);
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
    const found = validateRetrieval(draft, r.budget_ceilings, r.budgets);
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
  return (
    <form onSubmit={submit} noValidate className="mt-6">
      <FormAlert id="ai-alert" message={problem?.message} link={problem?.link} />
      <div className="flex flex-col gap-5">
        <label className="inline-flex min-h-11 cursor-pointer items-center gap-2.5 self-start text-sm font-medium md:min-h-8">
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
          Use AI providers for this library
        </label>
        {off && (
          <p className="fade-in -mt-3 text-sm text-muted-foreground">
            Off: no chunk, query or file of this library is sent to any provider, and its searches
            use BM25.
          </p>
        )}
        <SelectField
          id="ai-mode"
          label="Retrieval mode"
          value={draft.mode}
          error={errors.mode}
          hint="A search can still ask for another mode. Only modes that can run now are listed."
          onChange={(e) => edit({ mode: e.target.value })}
        >
          <option value="">
            {r.instance_mode
              ? `The instance's default (${MODE_LABEL[r.instance_mode]})`
              : "The best mode available"}
          </option>
          {modeOptions(r, draft).map((o) => (
            <option key={o.value} value={o.value} disabled={o.disabled}>
              {o.label}
            </option>
          ))}
        </SelectField>
        {/* A legend is no flex item: the fieldset stays a block and the fields get their own box. */}
        <fieldset disabled={off} className="disabled:opacity-60">
          <legend className="mb-1 text-sm font-medium">Models</legend>
          <p className="text-sm text-muted-foreground">
            Use another profile's model than the instance's. The embedding model is the same for
            every library.
          </p>
          <div className="mt-5 flex flex-col gap-5">
            {providersError ? (
              <p role="alert" className="text-sm font-medium text-destructive">
                {providersError}
              </p>
            ) : providers === undefined ? (
              <p className="text-sm text-muted-foreground">Loading the profiles…</p>
            ) : null}
            {OVERRIDABLE.map((role) => (
              <RoleOverride
                key={role}
                role={role}
                draft={draft}
                providers={providers}
                error={errors[role]}
                onChange={(value) => edit({ [role]: value })}
              />
            ))}
            <Field
              id="ai-rerankTopN"
              label="Candidates to rerank"
              inputMode="numeric"
              value={draft.rerankTopN}
              placeholder={String(r.effective_rerank_top_n)}
              error={errors.rerankTopN}
              hint={`1 to ${MAX_RERANK_TOP_N}. Empty: the instance's number.`}
              onChange={(e) => edit({ rerankTopN: e.target.value })}
            />
          </div>
        </fieldset>
        <SelectField
          id="ai-repoGuidance"
          label="Repository guidance (AGENTS.md / CLAUDE.md)"
          value={draft.repoGuidance}
          disabled={off}
          hint={`${REPO_GUIDANCE.find((g) => g.value === draft.repoGuidance)?.hint ?? ""} Applies to versions imported from now on.`}
          onChange={(e) => edit({ repoGuidance: e.target.value as RepoGuidance })}
        >
          {REPO_GUIDANCE.map((g) => (
            <option key={g.value} value={g.value}>
              {g.label}
            </option>
          ))}
        </SelectField>
        <fieldset>
          <legend className="mb-1 text-sm font-medium">Spend limits</legend>
          <p className="text-sm text-muted-foreground">
            Per UTC day and month. Once one is used up, searches skip the paid step and say why.
            Empty: only the instance's limits apply.
          </p>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <Field
              id="ai-dailyUsd"
              label="US dollars per day"
              inputMode="decimal"
              value={draft.dailyUsd}
              error={errors.dailyUsd}
              hint={ceilingHint(r.budget_ceilings, "daily_usd", "USD", r.budgets)}
              onChange={(e) => edit({ dailyUsd: e.target.value })}
            />
            <Field
              id="ai-monthlyUsd"
              label="US dollars per month"
              inputMode="decimal"
              value={draft.monthlyUsd}
              error={errors.monthlyUsd}
              hint={ceilingHint(r.budget_ceilings, "monthly_usd", "USD", r.budgets)}
              onChange={(e) => edit({ monthlyUsd: e.target.value })}
            />
            <Field
              id="ai-dailyTokens"
              label="Tokens per day"
              inputMode="numeric"
              value={draft.dailyTokens}
              error={errors.dailyTokens}
              hint={ceilingHint(r.budget_ceilings, "daily_tokens", "tokens", r.budgets)}
              onChange={(e) => edit({ dailyTokens: e.target.value })}
            />
            <Field
              id="ai-monthlyTokens"
              label="Tokens per month"
              inputMode="numeric"
              value={draft.monthlyTokens}
              error={errors.monthlyTokens}
              hint={ceilingHint(r.budget_ceilings, "monthly_tokens", "tokens", r.budgets)}
              onChange={(e) => edit({ monthlyTokens: e.target.value })}
            />
          </div>
        </fieldset>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button
            type="submit"
            aria-disabled={save.isPending || unchanged}
            aria-busy={save.isPending}
            className="min-w-32 aria-disabled:cursor-default"
          >
            {save.isPending ? "Saving" : "Save AI settings"}
          </Button>
          <p role="status" className="min-h-5 text-sm">
            {done && unchanged && activity.by === "ai" && (
              <span className="fade-in inline-flex items-center gap-1.5">
                <Check aria-hidden="true" className="size-4 text-mark" />
                Saved.
              </span>
            )}
          </p>
        </div>
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
  const value = draft[role];
  const label = ROLE_LABEL[role];
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <SelectField
        id={`ai-${role}-profile`}
        label={`${label} profile`}
        value={value.profile}
        // Until the profiles are read only the stored one is offered, never marked missing.
        disabled={providers === undefined}
        onChange={(e) => onChange({ profile: e.target.value, model: value.model })}
      >
        <option value="">
          {role === "judge" ? "The instance's (else the LLM)" : "The instance's"}
        </option>
        {profileOptions(providers, value.profile).map((p) => (
          <option key={p.value} value={p.value}>
            {p.value}
            {p.note}
          </option>
        ))}
      </SelectField>
      {value.profile ? (
        <Field
          id={`ai-${role}`}
          label={`${label} model`}
          autoComplete="off"
          value={value.model}
          error={error}
          onChange={(e) => onChange({ profile: value.profile, model: e.target.value })}
        />
      ) : null}
    </div>
  );
}
