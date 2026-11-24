import { createFileRoute } from "@tanstack/react-router";
import { GlobalSearchPage } from "@/features/search";
import { useMessages } from "@/shared/lib/i18n";
import { MAX_LIBRARY_ID, normalizeQuery } from "@/shared/lib/search-query";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { messages } from "./-messages";

const text = (value: unknown) => (typeof value === "string" && value !== "" ? value : undefined);

export const Route = createFileRoute("/_app/search")({
  validateSearch: (
    raw: Record<string, unknown>,
  ): { q?: string | undefined; library?: string | undefined } => ({
    q: normalizeQuery(text(raw.q)),
    // Over-long values are dropped, not sent: the API would answer 422.
    library: ((v) => (v && v.length <= MAX_LIBRARY_ID ? v : undefined))(text(raw.library)),
  }),
  component: function Search() {
    const { q, library } = Route.useSearch();
    const t = useMessages(messages);
    usePageTitle(q ? t.searchFor(q) : t.searchTitle);
    return <GlobalSearchPage q={q} {...(library && { library })} />;
  },
});
