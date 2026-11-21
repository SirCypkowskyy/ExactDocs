import { Link } from "@tanstack/react-router";
import { useEffect, useId, useState } from "react";
import { HttpError } from "@/shared/lib/http";
import { streamAnswer } from "../api/answer-stream";
import {
  type AnswerProgress,
  type AnswerResult,
  type AnswerSource,
  noAnswerSentence,
  spendSentence,
  splitLibrary,
} from "../model/playground";

type State =
  | { status: "running"; progress: AnswerProgress | null }
  | { status: "done"; result: AnswerResult }
  | { status: "failed"; message: string };

/** Runs the agent for a question over the libraries; leaving the page or a new run cancels it. */
function useAnswer(q: string, libraries: readonly string[]): State {
  const [state, setState] = useState<State>({ status: "running", progress: null });
  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "running", progress: null });
    streamAnswer(
      { question: q, libraries },
      (progress) => setState({ status: "running", progress }),
      controller.signal,
    )
      .then((result) => setState({ status: "done", result }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message = error instanceof Error ? error.message : "The agent failed.";
        setState({
          status: "failed",
          message:
            error instanceof HttpError && error.code === "mode_unavailable"
              ? `Unavailable: ${message}`
              : message,
        });
      });
    return () => controller.abort();
  }, [q, libraries]);
  return state;
}

function Source({ source }: { source: AnswerSource }) {
  const { owner, repo } = splitLibrary(source.library);
  return (
    <li className="space-y-1 rounded-md border border-border p-3">
      <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{source.library}</span>
        <span>
          <span className="sr-only">version </span>
          {source.version}
        </span>
      </div>
      <Link
        to="/libraries/$owner/$repo"
        params={{ owner, repo }}
        search={{ version: source.version, path: source.article_path }}
        {...(source.anchor ? { hash: source.anchor } : {})}
        className="block rounded-md text-sm font-medium underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
      >
        {source.heading_path.length > 0 ? source.heading_path.join(" › ") : source.article_path}
      </Link>
      <p className="font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">
        {source.article_path}
      </p>
      {source.quote && (
        <blockquote className="border-l-2 border-border pl-3 text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">
          {source.quote}
        </blockquote>
      )}
      <p className="text-sm text-muted-foreground">{source.reason}</p>
    </li>
  );
}

function Answered({ result }: { result: AnswerResult }) {
  const { usage } = result;
  return (
    <>
      {result.fallback_reason ? (
        <p className="rounded-md bg-accent px-3 py-2 text-sm">
          No answer: {noAnswerSentence(result.fallback_reason)}{" "}
          <span className="font-mono text-xs">({result.fallback_reason})</span>
        </p>
      ) : (
        <p className="text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">{result.answer}</p>
      )}
      {result.libraries_without_ai.length > 0 && (
        <p className="text-sm text-muted-foreground">
          Not read (AI is off for them): {result.libraries_without_ai.join(", ")}
        </p>
      )}
      <p className="text-sm text-muted-foreground tabular-nums">
        {usage.tool_calls} of {usage.max_tool_calls} tool calls · {spendSentence(usage)}
      </p>
      {result.sources.length > 0 && (
        <>
          <h3 className="text-sm font-semibold">
            {result.fallback_reason ? "Read before it stopped" : "Sources"}
          </h3>
          <ol aria-label="Sources" className="space-y-2">
            {result.sources.map((source) => (
              <Source key={`${source.library}:${source.chunk_id}`} source={source} />
            ))}
          </ol>
        </>
      )}
    </>
  );
}

/**
 * The agent's answer to the playground's question: its progress (tool calls out of the limit)
 * while it works, then the answer (shown as text: it is model output), the sources it stands on
 * and what the run spent.
 */
export function AgentAnswer({ q, libraries }: { q: string; libraries: readonly string[] }) {
  const headingId = useId();
  const state = useAnswer(q, libraries);
  return (
    <section
      aria-labelledby={headingId}
      aria-busy={state.status === "running"}
      className="min-w-0 space-y-3"
    >
      <h2 id={headingId} className="text-base font-semibold">
        Agent answer
      </h2>
      {state.status === "running" && (
        <p role="status" className="text-sm text-muted-foreground">
          {state.progress
            ? `The agent has made ${state.progress.toolCalls} of ${state.progress.maxToolCalls} tool calls…`
            : "The agent is starting…"}
        </p>
      )}
      {state.status === "failed" && (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {state.message}
        </p>
      )}
      {state.status === "done" && <Answered result={state.result} />}
    </section>
  );
}
