import { createFileRoute } from "@tanstack/react-router";
import { GlobalSearchPage } from "@/features/search";
import { normalizeQuery } from "@/shared/lib/search-query";
import { usePageTitle } from "@/shared/lib/use-page-title";

const text = (value: unknown) => (typeof value === "string" && value !== "" ? value : undefined);

export const Route = createFileRoute("/_app/search")({
  validateSearch: (
    raw: Record<string, unknown>,
  ): { q?: string | undefined; library?: string | undefined } => ({
    q: normalizeQuery(text(raw.q)),
    library: text(raw.library)?.slice(0, 256),
  }),
  component: function Search() {
    const { q, library } = Route.useSearch();
    usePageTitle(q ? `Search: ${q}` : "Search");
    return <GlobalSearchPage q={q} {...(library && { library })} />;
  },
});
