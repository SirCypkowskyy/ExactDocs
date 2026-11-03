import { API_BASE_URL } from "@/shared/config/env";

export class HttpError extends Error {
  readonly status: number;
  readonly path: string;

  constructor(status: number, path: string) {
    super(`Request to ${path} failed with status ${status}`);
    this.name = "HttpError";
    this.status = status;
    this.path = path;
  }
}

/** Typed JSON GET against the ExactDocs API. Validating the payload is the calling slice's job. */
export async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });
  if (!response.ok) {
    throw new HttpError(response.status, path);
  }
  return (await response.json()) as T;
}
