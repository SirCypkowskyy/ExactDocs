import { QueryClient } from "@tanstack/react-query";
import { HttpError } from "@/shared/lib/http";

const MAX_RETRIES = 2;

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Client errors (4xx) will not fix themselves; only retry network and server failures.
        retry: (failureCount, error) =>
          !(error instanceof HttpError && error.status < 500) && failureCount < MAX_RETRIES,
      },
    },
  });
}
