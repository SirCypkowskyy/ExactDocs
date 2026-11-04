import { API_BASE_URL } from "@/shared/config/env";
import type { components, paths } from "./api-schema";

/** The API's error envelope: a stable code, a sentence, and per-field problems. */
export type ErrorBody = components["schemas"]["ErrorResponse"];

type StripBase<P> = P extends `${typeof API_BASE_URL}${infer Rest}` ? Rest : never;
/** A `{param}` accepts any string (`/v1/tokens/abc`); that is loose: callers must encode it. */
type Fill<P> = P extends `${infer A}{${string}}${infer B}` ? `${A}${string}${Fill<B>}` : P;
/** A route that exists in the generated schema, relative to the API base (`/v1/session`). */
export type ApiPath = Fill<StripBase<keyof paths>>;

export class HttpError extends Error {
  readonly status: number;
  readonly path: string;
  /** The API's error code (`invalid_credentials`, `setup_required`...), when the body had one. */
  readonly code: string | undefined;
  readonly fields: ErrorBody["fields"];

  constructor(status: number, path: string, body?: Partial<ErrorBody>) {
    super(body?.detail ?? `Request to ${path} failed with status ${status}`);
    this.name = "HttpError";
    this.status = status;
    this.path = path;
    this.code = body?.error;
    this.fields = body?.fields ?? [];
  }
}

async function request<T>(path: ApiPath, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init.headers },
  });
  if (!response.ok) {
    throw new HttpError(response.status, path, await response.json().catch(() => undefined));
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** Typed JSON GET against the ExactDocs API. Validating the payload is the calling slice's job. */
export function getJson<T>(path: ApiPath, init?: RequestInit): Promise<T> {
  return request<T>(path, { ...init, credentials: "same-origin" });
}

/** JSON POST/DELETE against the ExactDocs API (the session cookie rides along, same-origin). */
export function sendJson<T>(
  method: "POST" | "PUT" | "DELETE",
  path: ApiPath,
  body?: unknown,
): Promise<T> {
  return request<T>(path, {
    method,
    credentials: "same-origin",
    // A response may carry a one-time secret (new API token): never let the HTTP cache keep it.
    cache: "no-store",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? null : JSON.stringify(body),
  });
}
