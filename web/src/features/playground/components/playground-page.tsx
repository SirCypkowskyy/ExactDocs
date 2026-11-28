import { useQuery } from "@tanstack/react-query";
import { FlaskConical, Search, Sparkles } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { common, useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Button } from "@/shared/ui/button";
import { Field } from "@/shared/ui/field";
import { LibraryCombobox, type LibraryOption } from "@/shared/ui/library-combobox";
import { Page, PageHeader } from "@/shared/ui/page";
import { SelectField } from "@/shared/ui/select-field";
import {
  answerAvailabilityQueryOptions,
  playgroundLibrariesQueryOptions,
} from "../api/playground-queries";
import { playgroundHelp } from "../help";
import { messages } from "../messages";
import {
  AGENT,
  PLAYGROUND_MODES,
  type PlaygroundChoice,
  type PlaygroundMode,
  type PlaygroundRun,
  searchableLibraries,
} from "../model/playground";
import { AgentAnswer } from "./agent-answer";
import { LibraryLogos } from "./library-logos";
import { ModeResults } from "./mode-results";

function ModeSelect({
  id,
  label,
  value,
  onChange,
  agent,
}: {
  id: string;
  label: string;
  value: PlaygroundChoice;
  onChange: (mode: PlaygroundChoice) => void;
  /** The agent option: absent leaves it out, `""` offers it, a reason shows it disabled. */
  agent?: string | undefined;
}) {
  const t = useMessages(messages);
  return (
    <SelectField
      id={id}
      label={label}
      value={value}
      hint={agent ? t.page.agentUnavailable(agent) : undefined}
      onChange={(e) => onChange(e.target.value as PlaygroundChoice)}
    >
      {PLAYGROUND_MODES.map((m) => (
        <option key={m} value={m}>
          {t.modes[m]}
        </option>
      ))}
      {agent !== undefined && (
        <option value={AGENT} disabled={agent !== ""}>
          {agent === "" ? t.page.agentOption : t.page.agentOptionUnavailable}
        </option>
      )}
    </SelectField>
  );
}

/** Runs the query: a search in the chosen modes, or a question to the agent. */
function RunButton({ agent, disabled }: { agent: boolean; disabled: boolean }) {
  const t = useMessages(messages);
  const c = useMessages(common);
  return (
    <Button type="submit" disabled={disabled}>
      {agent ? (
        <Sparkles aria-hidden="true" data-icon-motion="pop" />
      ) : (
        <Search aria-hidden="true" data-icon-motion="tilt" />
      )}
      {agent ? t.page.ask : c.search}
    </Button>
  );
}

/**
 * The search playground (#428): one query over all, one or several libraries, in one retrieval
 * mode or two side by side, with each result's BM25 and vector ranks and why a mode fell back.
 */
export function PlaygroundPage() {
  const t = useMessages(messages);
  const heading = usePageTitle(t.page.title);
  const librariesQuery = useQuery(playgroundLibrariesQueryOptions());
  const summaries = librariesQuery.data;
  const logos = useMemo(
    () => new Map((summaries ?? []).map((l) => [l.id, l.logo] as const)),
    [summaries],
  );
  // The picker offers the libraries that can be searched (a default version), by ID.
  const options = useMemo((): LibraryOption[] | undefined => {
    if (!summaries) return undefined;
    const byId = new Map(summaries.map((l) => [l.id, l]));
    return searchableLibraries(summaries).map((id) => ({
      id,
      title: byId.get(id)?.title,
      logo: byId.get(id)?.logo,
    }));
  }, [summaries]);
  const [q, setQ] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const { data: availability } = useQuery(answerAvailabilityQueryOptions());
  const [mode, setMode] = useState<PlaygroundChoice>("hybrid");
  const [compare, setCompare] = useState(false);
  const [other, setOther] = useState<PlaygroundMode>("bm25");
  const [run, setRun] = useState<PlaygroundRun | null>(null);
  // Until the endpoint has said, the agent is not offered; once it has, a reason disables it.
  const agentOffer = availability
    ? availability.available
      ? ""
      : (availability.reason ?? t.page.agentCantRun)
    : undefined;
  const agentChosen = mode === AGENT;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = q.trim();
    if (!text) return;
    setRun({
      q: text,
      libraries: chosen,
      first: mode,
      ...(compare && !agentChosen && { second: other }),
    });
  };

  return (
    <LibraryLogos.Provider value={logos}>
      <Page>
        <PageHeader
          icon={<FlaskConical />}
          help={playgroundHelp}
          title={t.page.title}
          headingRef={heading}
          description={t.page.description}
        />
        <form
          onSubmit={submit}
          className="max-w-3xl space-y-5 rounded-lg border border-border bg-raised p-5"
          aria-label={t.page.form}
        >
          <div data-tour="playground-query">
            <Field
              id="playground-q"
              label={t.page.query}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t.page.queryPlaceholder}
              maxLength={2000}
            />
          </div>
          <div data-tour="playground-libraries">
            <LibraryCombobox
              multiple
              label={t.page.libraries}
              placeholder={t.page.allLibraries}
              options={options}
              loading={librariesQuery.isPending}
              failed={librariesQuery.isError}
              onRetry={() => void librariesQuery.refetch()}
              value={chosen}
              onChange={setChosen}
              className="max-w-md"
            />
          </div>
          <div data-tour="playground-mode" className="grid gap-4 sm:grid-cols-2">
            <ModeSelect
              id="playground-mode"
              label={t.page.mode}
              value={mode}
              onChange={setMode}
              agent={agentOffer}
            />
            {compare && !agentChosen && (
              <ModeSelect
                id="playground-other"
                label={t.page.compareWith}
                value={other}
                onChange={(m) => setOther(m as PlaygroundMode)}
              />
            )}
          </div>
          {agentChosen ? (
            <p className="text-body text-muted-foreground">{t.page.agentNote}</p>
          ) : (
            <label
              data-tour="playground-compare"
              className="flex min-h-11 cursor-pointer items-center gap-2.5 text-body md:min-h-9"
            >
              <input
                type="checkbox"
                checked={compare}
                onChange={(e) => setCompare(e.target.checked)}
                className="size-4 cursor-pointer accent-primary"
              />
              {t.page.compare}
            </label>
          )}
          <RunButton agent={agentChosen} disabled={!q.trim()} />
        </form>
        {run && run.first === AGENT && (
          <div className="mt-8 max-w-3xl">
            <AgentAnswer q={run.q} libraries={run.libraries} />
          </div>
        )}
        {run && run.first !== AGENT && (
          <div className={run.second ? "mt-8 grid gap-8 lg:grid-cols-2" : "mt-8 max-w-3xl"}>
            <ModeResults q={run.q} mode={run.first} libraries={run.libraries} />
            {run.second && <ModeResults q={run.q} mode={run.second} libraries={run.libraries} />}
          </div>
        )}
      </Page>
    </LibraryLogos.Provider>
  );
}
