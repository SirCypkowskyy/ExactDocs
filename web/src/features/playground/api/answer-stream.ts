import { API_BASE_URL } from "@/shared/config/env";
import { HttpError } from "@/shared/lib/http";
import type { AnswerProgress, AnswerResult } from "../model/playground";

/** The code of the error thrown when the stream closes before its `answer` event. */
export const STREAM_ENDED = "stream_ended";

interface ProgressEvent {
  tool_calls: number;
  max_tool_calls: number;
}

/** The pieces of one server-sent event: its name and its data lines joined. */
function parseEvent(block: string): { name: string; data: string } {
  let name = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return { name, data: data.join("\n") };
}

/**
 * Ask the agent over the chosen libraries, hearing its tool calls as it works.
 * Resolves with the answer; rejects with an `HttpError` for a refused call or an `error` event.
 * Aborting the signal closes the stream, which cancels the run.
 */
export async function streamAnswer(
  body: { question: string; libraries: readonly string[] },
  onProgress: (progress: AnswerProgress) => void,
  signal: AbortSignal,
): Promise<AnswerResult> {
  const path = "/v1/answer/stream";
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    signal,
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => undefined);
    throw new HttpError(response.status, path, error);
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += value.replaceAll("\r\n", "\n");
    let end = buffer.indexOf("\n\n");
    while (end !== -1) {
      const event = parseEvent(buffer.slice(0, end));
      buffer = buffer.slice(end + 2);
      if (event.name === "progress") {
        const p = JSON.parse(event.data) as ProgressEvent;
        onProgress({ toolCalls: p.tool_calls, maxToolCalls: p.max_tool_calls });
      } else if (event.name === "answer") {
        return JSON.parse(event.data) as AnswerResult;
      } else if (event.name === "error") {
        throw new HttpError(422, path, JSON.parse(event.data));
      }
      end = buffer.indexOf("\n\n");
    }
  }
  // A client-side code, so the page can say it in the UI's language.
  throw new HttpError(502, path, {
    error: STREAM_ENDED,
    detail: "The answer stream ended without an answer.",
  });
}
