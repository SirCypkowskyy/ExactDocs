import { useQuery } from "@tanstack/react-query";
import { FlaskConical, Search, Sparkles } from "lucide-react";
import { type FormEvent, useState } from "react";
import { common, useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Button } from "@/shared/ui/button";
import { Field } from "@/shared/ui/field";
import { Page, PageHeader } from "@/shared/ui/page";
import { SelectField } from "@/shared/ui/select-field";
import {
  answerAvailabilityQueryOptions,
  playgroundLibrariesQueryOptions,
} from "../api/playground-queries";
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
import { ModeResults } from "./mode-results";

function LibraryPicker({
  libraries,
  chosen,
  onChange,
}: {
  libraries: readonly string[];
  chosen: readonly string[];
  onChange: (next: string[]) => void;
}) {
  const t = useMessages(messages);
  const picked = new Set(chosen);
  const toggle = (id: string) =>
    onChange(picked.has(id) ? chosen.filter((c) => c !== id) : [...chosen, id]);
  return (
    <fieldset className="space-y-2">
      <legend className="text-body font-medium">{t.page.libraries}</legend>
      <div className="flex flex-wrap gap-x-5 gap-y-1">
        <label className="flex min-h-11 cursor-pointer items-center gap-2.5 text-body md:min-h-9">
          <input
            type="checkbox"
            checked={chosen.length === 0}
            onChange={() => onChange([])}
            className="size-4 cursor-pointer accent-primary"
          />
          {t.page.allLibraries}
        </label>
        {libraries.map((id) => (
          <label
            key={id}
            className="flex min-h-11 cursor-pointer items-center gap-2.5 text-body md:min-h-9"
          >
            <input
              type="checkbox"
              checked={picked.has(id)}
              onChange={() => toggle(id)}
              className="size-4 cursor-pointer accent-primary"
            />
            <span className="font-mono text-mono">{id}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

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
  const { data: summaries } = useQuery(playgroundLibrariesQueryOptions());
  const libraries = searchableLibraries(summaries ?? []);
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
    <Page>
      <PageHeader
        icon={<FlaskConical />}
        title={t.page.title}
        headingRef={heading}
        description={t.page.description}
      />
      <form
        onSubmit={submit}
        className="max-w-3xl space-y-5 rounded-lg border border-border bg-raised p-5"
        aria-label={t.page.form}
      >
        <Field
          id="playground-q"
          label={t.page.query}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t.page.queryPlaceholder}
          maxLength={2000}
        />
        <LibraryPicker libraries={libraries} chosen={chosen} onChange={setChosen} />
        <div className="grid gap-4 sm:grid-cols-2">
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
          <label className="flex min-h-11 cursor-pointer items-center gap-2.5 text-body md:min-h-9">
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
  );
}
