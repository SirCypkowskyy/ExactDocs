import { useSuspenseQuery } from "@tanstack/react-query";
import { librariesQueryOptions } from "../api/libraries-query";

export function useLibraries() {
  return useSuspenseQuery(librariesQueryOptions());
}
