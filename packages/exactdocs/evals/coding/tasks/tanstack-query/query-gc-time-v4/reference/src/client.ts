import { QueryClient } from "@tanstack/query-core";

/** The app's query client. */
export function createClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, cacheTime: 100 } },
  });
}
