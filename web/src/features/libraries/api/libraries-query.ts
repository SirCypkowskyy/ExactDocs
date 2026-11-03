import { queryOptions } from "@tanstack/react-query";
import { getJson } from "@/shared/lib/http";
import type { LibrariesResponse } from "../model/library";

const librariesKeys = {
  all: ["libraries"] as const,
  list: () => [...librariesKeys.all, "list"] as const,
};

export const librariesQueryOptions = () =>
  queryOptions({
    queryKey: librariesKeys.list(),
    queryFn: ({ signal }) => getJson<LibrariesResponse>("/v1/libraries", { signal }),
    select: (data) => data.libraries,
  });
