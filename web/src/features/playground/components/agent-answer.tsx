import { useEffect, useId, useState } from "react";
import { HttpError } from "@/shared/lib/http";
import { streamAnswer } from "../api/answer-stream";
import {
  type AnswerProgress,
  type AnswerResult,
  type AnswerSource,
  noAnswerSentence,
  spendSentence,
} from "../model/playground";
import { Notice, ResultHead, ResultsSkeleton, resultCard, resultList } from "./parts";

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
  return (
    <li className={resultCard}>
      <ResultHead
        library={source.library}
        version={source.version}
        articlePath={source.article_path}
        anchor={source.anchor}
        headingPath={source.heading_path}
      />
      {source.quote && (
        <blockquote className="mt-2 rounded-md bg-raised px-3 py-1.5 text-body whitespace-pre-wrap [overflow-wrap:anywhere]">
          {source.quote}
        </blockquote>
      )}
      <p className="mt-2 text-body text-muted-foreground">{source.reason}</p>
    </li>
  );
}

function Answered({ result }: { result: AnswerResult }) {
  const { usage } = result;
  return (
    <>
      {result.fallback_reason ? (
        <Notice tone="note">
          No answer: {noAnswerSentence(result.fallback_reason)}{" "}
          <span className="font-mono text-mono">({result.fallback_reason})</span>
        </Notice>
      ) : (
        <p className="max-w-[68ch] text-section whitespace-pre-wrap [overflow-wrap:anywhere]">
          {result.answer}
        </p>
      )}
      {result.libraries_without_ai.length > 0 && (
        <p className="text-body text-muted-foreground">
          Not read (AI is off for them): {result.libraries_without_ai.join(", ")}
        </p>
      )}
      <p className="text-body text-muted-foreground tabular-nums">
        {usage.tool_calls} of {usage.max_tool_calls} tool calls · {spendSentence(usage)}
      </p>
      {result.sources.length > 0 && (
        <>
          <h3 className="pt-2 text-section font-semibold">
            {result.fallback_reason ? "Read before it stopped" : "Sources"}
          </h3>
          <ol aria-label="Sources" className={resultList}>
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
      <h2 id={headingId} className="text-section font-semibold">
        Agent answer
      </h2>
      {state.status === "running" && (
        <>
          <p role="status" className="text-body text-muted-foreground">
            {state.progress
              ? `The agent has made ${state.progress.toolCalls} of ${state.progress.maxToolCalls} tool calls…`
              : "The agent is starting…"}
          </p>
          <ResultsSkeleton />
        </>
      )}
      {state.status === "failed" && <Notice tone="error">{state.message}</Notice>}
      {state.status === "done" && <Answered result={state.result} />}
    </section>
  );
}
