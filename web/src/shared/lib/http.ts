import { API_BASE_URL } from "@/shared/config/env";
import type { components, paths } from "./api-schema";

/** The API's error envelope: a stable code, a sentence, and per-field problems. */
export type ErrorBody = components["schemas"]["ErrorResponse"];

type StripBase<P> = P extends `${typeof API_BASE_URL}${infer Rest}` ? Rest : never;
/** A `{param}` accepts any string (`/v1/tokens/abc`); that is loose: callers must encode it. */
type Fill<P> = P extends `${infer A}{${string}}${infer B}` ? `${A}${string}${Fill<B>}` : P;
/** A route that exists in the generated schema, relative to the API base (`/v1/session`). */
type Route = Fill<StripBase<keyof paths>>;
/** A route, optionally with a query string (`/v1/repositories/refs?url=...`). */
export type ApiPath = Route | `${Route}?${string}`;

export class HttpError extends Error {
  readonly status: number;
  readonly path: string;
  /** The API's error code (`invalid_credentials`, `setup_required`...), when the body had one. */
  readonly code: string | undefined;
  readonly fields: ErrorBody["fields"];
  /** On a missing article: paths of the same version it may have meant (repository data). */
  readonly closeMatches: readonly string[];

  constructor(status: number, path: string, body?: Partial<ErrorBody>) {
    super(body?.detail ?? `Request to ${path} failed with status ${status}`);
    this.name = "HttpError";
    this.status = status;
    this.path = path;
    this.code = body?.error;
    this.fields = body?.fields ?? [];
    this.closeMatches = body?.close_matches ?? [];
  }
}

/** The query parameters the schema declares for `GET` on a route (`/api/v1/...`): check an object against it. */
export type QueryOf<P extends keyof paths> = NonNullable<
  paths[P] extends { get: { parameters: { query?: infer Q } } } ? Q : never
>;

/**
 * Query parameters; `undefined`, `null` and empty arrays are left out. An array is comma-joined,
 * which the API reads as separate values, so a value containing a comma would be split in two.
 */
export type Query = Record<string, string | number | readonly string[] | null | undefined>;

function queryString(query: Query | undefined): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || (Array.isArray(value) && value.length === 0)) {
      continue;
    }
    params.set(key, Array.isArray(value) ? value.join(",") : String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

async function request<T>(path: ApiPath, init: RequestInit, query?: Query): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}${queryString(query)}`, {
    ...init,
    headers: { Accept: "application/json", ...init.headers },
  });
  if (!response.ok) {
    throw new HttpError(response.status, path, await response.json().catch(() => undefined));
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** Typed JSON GET against the ExactDocs API. Validating the payload is the calling slice's job. */
export function getJson<T>(path: ApiPath, init?: RequestInit & { query?: Query }): Promise<T> {
  const { query, ...rest } = init ?? {};
  return request<T>(path, { ...rest, credentials: "same-origin" }, query);
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
