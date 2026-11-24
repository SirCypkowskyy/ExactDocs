import { parseTags } from "@/shared/lib/tags";
import type { TableConfig, TableSearch } from "@/shared/ui/data-table/table-search";
import type { BrowseSearch } from "./browse";

/** The fields `GET .../articles` sorts by. */
export const ARTICLE_SORTS = ["path", "title", "size"] as const;

/** The articles table (DataTable v2): sorted by path unless the URL says otherwise. */
export const ARTICLES_TABLE: TableConfig = {
  id: "articles",
  sortFields: ARTICLE_SORTS,
  defaultSort: "path",
};

/**
 * The table's view, read from the library page's URL. The page's `q` is the version's search
 * (its results replace the table), so the table's text filter lives in `filter` and is handed to
 * the table as its `q`.
 */
export interface ArticlesView extends TableSearch {
  tags?: string[] | undefined;
  prefix?: string | undefined;
}

export const articlesView = (search: BrowseSearch): ArticlesView => {
  const tags = parseTags(search.tags);
  return {
    q: search.filter,
    sort: search.sort,
    page: search.page,
    size: search.size,
    tags: tags.length ? tags : undefined,
    prefix: search.prefix,
  };
};

/** What `GET .../articles` filters and sorts by: the view without its page and size. */
export interface ArticleFilters {
  q?: string;
  tags: readonly string[];
  prefix?: string;
  sort?: string;
}

export const articleFilters = (view: ArticlesView): ArticleFilters => ({
  ...(view.q && { q: view.q }),
  tags: view.tags ?? [],
  ...(view.prefix && { prefix: view.prefix }),
  ...(view.sort && { sort: view.sort }),
});

/** `docs/guide/auth.md` -> `docs/guide`; empty for a file at the root. */
export const folderOf = (path: string) => path.slice(0, Math.max(0, path.lastIndexOf("/")));
