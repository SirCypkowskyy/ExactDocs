import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Button } from "@/shared/ui/button";
import { Field } from "@/shared/ui/field";
import { SelectField } from "@/shared/ui/select-field";
import { playgroundLibrariesQueryOptions } from "../api/playground-queries";
import {
  MODE_LABEL,
  PLAYGROUND_MODES,
  type PlaygroundMode,
  type PlaygroundRun,
  searchableLibraries,
} from "../model/playground";
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
  const picked = new Set(chosen);
  const toggle = (id: string) =>
    onChange(picked.has(id) ? chosen.filter((c) => c !== id) : [...chosen, id]);
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">Libraries</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-2">
        <label className="flex min-h-11 items-center gap-2 text-sm lg:min-h-8">
          <input
            type="checkbox"
            checked={chosen.length === 0}
            onChange={() => onChange([])}
            className="size-4 accent-[var(--color-mark)]"
          />
          All libraries
        </label>
        {libraries.map((id) => (
          <label key={id} className="flex min-h-11 items-center gap-2 text-sm lg:min-h-8">
            <input
              type="checkbox"
              checked={picked.has(id)}
              onChange={() => toggle(id)}
              className="size-4 accent-[var(--color-mark)]"
            />
            <span className="font-mono text-xs">{id}</span>
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
}: {
  id: string;
  label: string;
  value: PlaygroundMode;
  onChange: (mode: PlaygroundMode) => void;
}) {
  return (
    <SelectField
      id={id}
      label={label}
      value={value}
      onChange={(e) => onChange(e.target.value as PlaygroundMode)}
    >
      {PLAYGROUND_MODES.map((m) => (
        <option key={m} value={m}>
          {MODE_LABEL[m]}
        </option>
      ))}
    </SelectField>
  );
}

/**
 * The search playground (#428): one query over all, one or several libraries, in one retrieval
 * mode or two side by side, with each result's BM25 and vector ranks and why a mode fell back.
 */
export function PlaygroundPage() {
  const { data: summaries } = useQuery(playgroundLibrariesQueryOptions());
  const libraries = searchableLibraries(summaries ?? []);
  const [q, setQ] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [mode, setMode] = useState<PlaygroundMode>("hybrid");
  const [compare, setCompare] = useState(false);
  const [other, setOther] = useState<PlaygroundMode>("bm25");
  const [run, setRun] = useState<PlaygroundRun | null>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = q.trim();
    if (!text) return;
    setRun({ q: text, libraries: chosen, first: mode, ...(compare && { second: other }) });
  };

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold tracking-tight">Search playground</h1>
        <p className="text-sm text-muted-foreground">
          Run one query across the libraries you choose and compare how BM25, vector and hybrid
          search rank it.
        </p>
      </header>
      <form onSubmit={submit} className="space-y-4" aria-label="Playground query">
        <Field
          id="playground-q"
          label="Query"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="how do I retry failed calls"
          maxLength={2000}
        />
        <LibraryPicker libraries={libraries} chosen={chosen} onChange={setChosen} />
        <div className="grid gap-4 sm:grid-cols-2">
          <ModeSelect id="playground-mode" label="Mode" value={mode} onChange={setMode} />
          {compare && (
            <ModeSelect
              id="playground-other"
              label="Compare with"
              value={other}
              onChange={setOther}
            />
          )}
        </div>
        <label className="flex min-h-11 items-center gap-2 text-sm lg:min-h-8">
          <input
            type="checkbox"
            checked={compare}
            onChange={(e) => setCompare(e.target.checked)}
            className="size-4 accent-[var(--color-mark)]"
          />
          Compare two modes side by side
        </label>
        <Button type="submit" disabled={!q.trim()}>
          Search
        </Button>
      </form>
      {run && (
        <div className={run.second ? "grid gap-6 lg:grid-cols-2" : ""}>
          <ModeResults q={run.q} mode={run.first} libraries={run.libraries} />
          {run.second && <ModeResults q={run.q} mode={run.second} libraries={run.libraries} />}
        </div>
      )}
    </main>
  );
}
