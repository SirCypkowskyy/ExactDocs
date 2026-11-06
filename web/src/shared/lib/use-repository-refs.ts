import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { Credential } from "./credentials";
import { sendJson } from "./http";
import { type RepositoryRefs, repositoryRefsQueryOptions } from "./refs";

interface Listed {
  data: RepositoryRefs | undefined;
  isPending: boolean;
  isError: boolean;
  /** Why the listing failed (an `HttpError` from the server, or a network error). */
  error: unknown;
  isFetching: boolean;
  refetch: () => unknown;
}

/** One listing with a credential, held by the component: never a query (its key, its cache). */
function usePrivateRefs(url: string, credential: Credential | undefined): Listed {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    data?: RepositoryRefs;
    error?: unknown;
    fetching: boolean;
  }>({ fetching: true });
  useEffect(() => {
    if (!credential) return;
    let live = true;
    setState((s) => ({ ...s, fetching: true }));
    // `attempt` re-runs this for "Try again".
    void attempt;
    sendJson<RepositoryRefs>("POST", "/v1/repositories/refs", { url, credential }).then(
      (data) => live && setState({ data, fetching: false }),
      (error: unknown) => live && setState({ error: error ?? new Error("refs"), fetching: false }),
    );
    return () => {
      live = false;
    };
  }, [url, credential, attempt]);
  return {
    data: state.data,
    isPending: !state.data && !state.error,
    isError: Boolean(state.error),
    error: state.error,
    isFetching: state.fetching,
    refetch: () => setAttempt((n) => n + 1),
  };
}

/**
 * The branches and tags of a repository. A public one is a cached query by URL; with a
 * credential the list is fetched with `POST` (the secret in the body, never in the URL) and kept
 * in component state, so the secret reaches no query key or cache. `enabled: false` asks nothing.
 */
export function useRepositoryRefs(
  url: string,
  credential: Credential | undefined,
  enabled = true,
): Listed {
  const query = useQuery({ ...repositoryRefsQueryOptions(url), enabled: enabled && !credential });
  const listed = usePrivateRefs(url, credential);
  if (credential) return listed;
  return enabled ? query : NOT_ASKED;
}

/** Not asked at all (a private repository with no credential at hand): only typing is left. */
const NOT_ASKED: Listed = {
  data: undefined,
  isPending: false,
  isError: true,
  error: undefined,
  isFetching: false,
  refetch: () => undefined,
};
