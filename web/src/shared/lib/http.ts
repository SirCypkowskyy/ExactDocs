import { API_BASE_URL } from "@/shared/config/env";

/** The API's error envelope (`ErrorResponse`): a stable code, a sentence, and per-field problems. */
export interface ErrorBody {
  error: string;
  detail: string;
  fields: { loc: (string | number)[]; msg: string; type: string }[];
}

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

async function request<T>(path: string, init: RequestInit): Promise<T> {
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
export function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, { ...init, credentials: "same-origin" });
}

/** JSON POST/DELETE against the ExactDocs API (the session cookie rides along, same-origin). */
export function sendJson<T>(
  method: "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  return request<T>(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? null : JSON.stringify(body),
  });
}
