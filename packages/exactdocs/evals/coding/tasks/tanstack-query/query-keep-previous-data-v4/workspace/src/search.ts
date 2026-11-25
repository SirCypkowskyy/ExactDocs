/** Runs a search. */
export type Search = (term: string) => Promise<string[]>;

/** The query of a search, which keeps showing the last results while the next load. */
export function searchOptions(search: Search, term: string) {
  return {
    queryKey: ["search", term],
    queryFn: () => search(term),
  };
}
