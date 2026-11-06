import { useMemo, useRef, useState } from "react";
import { lines, validatePatterns } from "@/shared/lib/path-selection";
import { addVersion, previewRepository } from "../api/add-library";
import {
  type AddProblem,
  buildFileTree,
  explainOlderVersionError,
  explainPreviewError,
  previewKey,
  type RepositoryPreview,
} from "../model/add-library";

export interface PreviewForm {
  url: string;
  ref: string | null;
  include: string;
  exclude: string;
}

interface Previewed {
  result: RepositoryPreview;
  /** `previewKey` of the form this preview answers. */
  key: string;
  /** The include and exclude boxes were filled from `context7.json`. */
  prefilled: boolean;
}

interface Callbacks {
  onFail: (problem: AddProblem) => void;
  /** The boxes were empty and `context7.json` gave paths: put them in the boxes. */
  onPrefill: (include: string, exclude: string) => void;
  /** A preview request is leaving: clear the old refusal. */
  onStart: () => void;
}

/** Empty boxes took the paths of context7.json: show them there, where they can be edited. */
function prefillOf(result: RepositoryPreview, form: PreviewForm) {
  const include = result.include_paths ?? [];
  const exclude = result.exclude_paths ?? [];
  const typed = lines(form.include).length + lines(form.exclude).length > 0;
  if (!result.context7 || typed || include.length + exclude.length === 0) return undefined;
  return { include: include.join("\n"), exclude: exclude.join("\n") };
}

/** The dry run of the add form: one preview on screen, only the latest request lands. */
export function usePreview({ onFail, onPrefill, onStart }: Callbacks) {
  const [preview, setPreview] = useState<Previewed>();
  // The run being waited for; a forgotten or replaced run never touches the screen again.
  const [waiting, setWaiting] = useState<number>();
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const run = useRef(0);
  const tree = useMemo(() => preview && buildFileTree(preview.result.files), [preview]);

  function forget() {
    run.current++;
    setPreview(undefined);
    setWaiting(undefined);
    setSelected(new Set());
  }

  async function start(form: PreviewForm) {
    if (waiting !== undefined) return;
    const paths = validatePatterns(form.include) ?? validatePatterns(form.exclude);
    if (paths) return onFail({ field: "paths", message: paths });
    const mine = ++run.current;
    onStart();
    setWaiting(mine);
    try {
      const result = await previewRepository({
        url: form.url,
        ...(form.ref && { ref: form.ref }),
        include_paths: lines(form.include),
        exclude_paths: lines(form.exclude),
      });
      if (run.current !== mine) return;
      const prefill = prefillOf(result, form);
      if (prefill) onPrefill(prefill.include, prefill.exclude);
      const offered = new Set(result.context7?.previous_versions.map((v) => v.tag) ?? []);
      setSelected((s) => new Set([...s].filter((tag) => offered.has(tag))));
      setPreview({
        result,
        key: previewKey({ ...form, ...prefill }),
        prefilled: Boolean(prefill),
      });
    } catch (error) {
      if (run.current === mine) onFail(explainPreviewError(error, form.ref));
    } finally {
      setWaiting((w) => (w === mine ? undefined : w));
    }
  }

  function select(tag: string, on: boolean) {
    setSelected((s) => {
      const next = new Set(s);
      if (on) next.add(tag);
      else next.delete(tag);
      return next;
    });
  }

  /** The ticked `previousVersions` tags, in the order the file lists them, minus the refs being added. */
  const chosen = (added: readonly (string | null)[]) => {
    const skip = new Set(added);
    return (preview?.result.context7?.previous_versions ?? [])
      .map((v) => v.tag)
      .filter((tag) => selected.has(tag) && !skip.has(tag));
  };

  return { preview, tree, pending: waiting !== undefined, selected, select, start, forget, chosen };
}

/** An older version queued after the library was added: its job, or why it was refused. */
export interface Extra {
  tag: string;
  jobId?: string;
  error?: string;
  /** Trying again can help (offline, server error); a refusal about the tag itself cannot. */
  retry?: boolean;
}

/** Queues the ticked older versions once the library exists; each one shows how it went. */
export function useOlderVersions() {
  const [extras, setExtras] = useState<Extra[]>([]);
  const run = useRef(0);
  const library = useRef("");

  function send(tag: string, mine: number) {
    const settle = (done: Extra) => {
      if (run.current === mine) setExtras((xs) => xs.map((x) => (x.tag === done.tag ? done : x)));
    };
    return addVersion(library.current, tag).then(
      (v) => settle({ tag, jobId: v.job_id }),
      (error: unknown) => {
        const why = explainOlderVersionError(error, tag);
        settle({ tag, error: `Not queued. ${why.message}`, retry: why.retry });
      },
    );
  }

  async function queue(libraryId: string, tags: readonly string[]) {
    const mine = ++run.current;
    library.current = libraryId;
    setExtras(tags.map((tag) => ({ tag })));
    await Promise.all(tags.map((tag) => send(tag, mine)));
  }

  /** One failed tag again; the others keep their state. */
  async function retry(tag: string) {
    setExtras((xs) => xs.map((x) => (x.tag === tag ? { tag } : x)));
    await send(tag, run.current);
  }

  function clear() {
    run.current++;
    setExtras([]);
  }

  return { extras, queue, retry, clear };
}
