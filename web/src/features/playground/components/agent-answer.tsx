import { useEffect, useId, useState } from "react";
import { HttpError } from "@/shared/lib/http";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { STREAM_ENDED, streamAnswer } from "../api/answer-stream";
import { messages, type PlaygroundMessages } from "../messages";
import {
  type AnswerProgress,
  type AnswerResult,
  type AnswerSource,
  noAnswerSentence,
} from "../model/playground";
import { Notice, ResultHead, ResultsSkeleton, resultCard, resultList } from "./parts";

type State =
  | { status: "running"; progress: AnswerProgress | null }
  | { status: "done"; result: AnswerResult }
  | { status: "failed"; error: unknown };

/** What a failed run says: the server's words, marked when the mode is unavailable. */
function failure(error: unknown, t: PlaygroundMessages): string {
  if (error instanceof HttpError && error.code === STREAM_ENDED) return t.agent.streamEnded;
  const message = error instanceof Error ? error.message : t.agent.failed;
  return error instanceof HttpError && error.code === "mode_unavailable"
    ? t.results.unavailable(message)
    : message;
}

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
        setState({ status: "failed", error });
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
  const t = useMessages(messages);
  const language = useLanguage();
  const { usage } = result;
  return (
    <>
      {result.fallback_reason ? (
        <Notice tone="note">
          {t.agent.noAnswer(noAnswerSentence(result.fallback_reason, language))}{" "}
          <span className="font-mono text-mono">({result.fallback_reason})</span>
        </Notice>
      ) : (
        <p className="max-w-[68ch] text-section whitespace-pre-wrap [overflow-wrap:anywhere]">
          {result.answer}
        </p>
      )}
      {result.libraries_without_ai.length > 0 && (
        <p className="text-body text-muted-foreground">
          {t.agent.notRead(result.libraries_without_ai.join(", "))}
        </p>
      )}
      <p className="text-body text-muted-foreground tabular-nums">
        {t.agent.toolCalls(usage.tool_calls, usage.max_tool_calls)} · {t.agent.spend(usage)}
      </p>
      {result.sources.length > 0 && (
        <>
          <h3 className="pt-2 text-section font-semibold">
            {result.fallback_reason ? t.agent.readBeforeStop : t.agent.sources}
          </h3>
          <ol aria-label={t.agent.sources} className={resultList}>
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
  const t = useMessages(messages);
  const headingId = useId();
  const state = useAnswer(q, libraries);
  return (
    <section
      aria-labelledby={headingId}
      aria-busy={state.status === "running"}
      className="min-w-0 space-y-3"
    >
      <h2 id={headingId} className="text-section font-semibold">
        {t.agent.heading}
      </h2>
      {state.status === "running" && (
        <>
          <p role="status" className="text-body text-muted-foreground">
            {state.progress
              ? t.agent.progress(state.progress.toolCalls, state.progress.maxToolCalls)
              : t.agent.starting}
          </p>
          <ResultsSkeleton />
        </>
      )}
      {state.status === "failed" && <Notice tone="error">{failure(state.error, t)}</Notice>}
      {state.status === "done" && <Answered result={state.result} />}
    </section>
  );
}
