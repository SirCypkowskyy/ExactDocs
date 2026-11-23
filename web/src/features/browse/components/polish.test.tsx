import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type ReactNode, Suspense } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { keptNotice } from "../model/article-tags";
import {
  type Article,
  type ArticleSummary,
  buildRows,
  type LibraryDetail,
  type Version,
} from "../model/browse";
import { ArticleView } from "./article-view";
import { BrowsePage } from "./browse-page";
import { FileTree } from "./file-tree";
import { LibraryNotFound } from "./library-not-found";
import { VersionPicker } from "./version-picker";

/*
 * The UI around the documentation speaks Polish when the person chose it; the documentation
 * itself (titles, text, paths, refs, a callout's own title) stays as the library wrote it.
 */

const SHA = "2af418f7206a048fd5c2c0b4f06330b0dd48b0ff";
const version = (ref: string, extra: Partial<Version> = {}): Version => ({
  ref,
  kind: "tag",
  commit_sha: SHA,
  imported_at: "2026-11-01T10:00:00Z",
  is_default: false,
  origin: "manual",
  ...extra,
});
const versions = [
  version("v1.4.0", { is_default: true }),
  ...["v1.3.0", "v1.2.0", "v1.1.0", "v1.0.0", "v0.9.0", "v0.8.0"].map((ref) => version(ref)),
  version("main", { kind: "branch" }),
];
const library = {
  id: "/acme/payments",
  title: "Acme Payments",
  description: "",
  source_url: "https://github.com/acme/payments",
  host: "github",
  default_branch: "main",
  default_pinned: false,
  settings: {},
  versions,
  default_version: "v1.4.0",
} as unknown as LibraryDetail;
const summaries: ArticleSummary[] = [
  { path: "docs/start.md", title: "Start", tags: [], size: 10 },
  { path: "docs/api.md", title: "API reference", tags: [], size: 2048 },
];
const article = {
  path: "docs/start.md",
  title: "Start",
  tags: [],
  tag_origins: [],
  manual_tags: [],
  front_matter: {},
  source_url: "https://github.com/acme/payments/blob/main/docs/start.md",
  content: [
    "# Start",
    "## Install",
    "```",
    "pnpm add payments",
    "```",
    '!!! tip "Use the sandbox"',
    "    Keys starting with `test_` never charge.",
    "## Reference",
    "| Field | Type |\n| --- | --- |\n| id | string |",
    "- [ ] Write the docs",
    "![Logo](https://example.com/logo.png)",
  ].join("\n\n"),
} as unknown as Article;

/** The library's API, as far as these screens ask it. */
function serve() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const { pathname } = new URL(input, "http://test");
      if (pathname.endsWith("/articles")) {
        return Response.json({ articles: summaries, next_cursor: null, total: summaries.length });
      }
      if (pathname.endsWith("/tags")) return Response.json({ tags: [], truncated: false });
      if (pathname.endsWith("/access")) return Response.json({ private: false });
      if (pathname.endsWith("/article")) return Response.json(article);
      return Response.json(library);
    }),
  );
}

let client: QueryClient;

function show(Page: () => ReactNode) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapped() {
    return (
      <QueryClientProvider client={client}>
        <Suspense fallback={null}>
          <Page />
        </Suspense>
      </QueryClientProvider>
    );
  }
  return render(<TestRouter pages={{ "/": Wrapped }} />);
}

// The renderer is a lazy chunk: load it up front, as the article tests do.
beforeAll(() => import("../render/markdown"));
beforeEach(() => setPreferences({ language: "pl" }));
afterEach(() => {
  resetPreferences();
  vi.unstubAllGlobals();
});

describe("browse in Polish", () => {
  it("shows the library page's chrome in Polish", async () => {
    serve();
    show(() => <BrowsePage owner="acme" repo="payments" search={{}} />);
    expect(await screen.findByRole("heading", { name: "Przeglądasz v1.4.0" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Ścieżka nawigacji" })).toHaveTextContent(
      "Biblioteki",
    );
    expect(screen.getByRole("link", { name: "Udostępnij" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ustawienia" })).toBeInTheDocument();
    expect(screen.getByText(/^Zaimportowano/)).toBeInTheDocument();
    expect(screen.getByText("Przeczytaj artykuł")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Artykuły" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Ścieżka/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Rozmiar/ })).toBeInTheDocument();
    // Sizes are written the Polish way: a decimal comma.
    expect(await screen.findByText("2,0 KB")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wersja: v1.4.0. Zmień wersję" })).toBeVisible();
    expect(await screen.findByRole("tree", { name: "Pliki wersji v1.4.0" })).toBeInTheDocument();
    // The library's own words stay as they are.
    expect(screen.getByRole("heading", { level: 1, name: "Acme Payments" })).toBeInTheDocument();
  });

  it("shows the article pane in Polish and leaves the documentation as written", async () => {
    serve();
    show(() => (
      <ArticleView
        owner="acme"
        repo="payments"
        library={library}
        version={versions[0] as Version}
        path="docs/start.md"
        tags={undefined}
      />
    ));
    const install = await screen.findByRole("heading", { name: /Install/ });
    // The documentation: untouched.
    expect(screen.getByRole("heading", { level: 2, name: "Start" })).toBeInTheDocument();
    expect(screen.getByText("Use the sandbox")).toBeInTheDocument();
    // The chrome around it, and the renderer's own labels: Polish.
    expect(within(install).getByRole("link", { name: "Link do nagłówka „Install”" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Podgląd" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Źródło" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Zobacz plik w serwisie GitHub/ })).toHaveTextContent(
      "w commicie 2af418f (otwiera się w nowej karcie)",
    );
    expect(screen.getByRole("region", { name: "Treść artykułu" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Tabela: Field" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Niewykonane" })).toBeInTheDocument();
    expect(screen.getByText("Obraz niedostępny: Logo")).toBeInTheDocument();
    expect(screen.getByText("Porada:", { exact: false })).toHaveClass("sr-only");
    expect(screen.getByText("Tekst")).toBeInTheDocument();
    expect(within(screen.getByRole("button", { name: /Kopiuj/ })).getByText("kod")).toHaveClass(
      "sr-only",
    );
    expect(await screen.findByText("2 sekcje")).toBeInTheDocument();
    expect(screen.getAllByRole("navigation", { name: "Na tej stronie" }).length).toBeGreaterThan(0);
    // The tag editor.
    expect(screen.getByRole("region", { name: "Tagi" })).toHaveTextContent("Dodane tutaj");
    await userEvent.click(screen.getByRole("button", { name: "Dodaj tag" }));
    expect(screen.getByLabelText("Nowy tag")).toHaveFocus();
    await userEvent.type(screen.getByLabelText("Nowy tag"), "-zly{Enter}");
    expect(screen.getByLabelText("Nowy tag")).toHaveAccessibleDescription(
      /^Tag zaczyna się od litery lub cyfry, .* \(najwyżej 40 znaków\)\./,
    );
    expect(screen.getByRole("button", { name: "Anuluj" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Źródło" }));
    expect(screen.getByRole("region", { name: "Tekst źródłowy" })).toBeInTheDocument();
  });

  it("says a missing article is not in the version, in Polish", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const { pathname } = new URL(input, "http://test");
        if (pathname.endsWith("/renamed-path")) return Response.json({ renamed: null });
        return Response.json(
          { error: "not_found", detail: "no article", fields: [], close_matches: ["docs/api.md"] },
          { status: 404 },
        );
      }),
    );
    show(() => (
      <ArticleView
        owner="acme"
        repo="payments"
        library={library}
        version={versions[1] as Version}
        path="docs/gone.md"
        tags={undefined}
      />
    ));
    expect(
      await screen.findByRole("heading", { name: "Brak w wersji v1.3.0" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Mógł zostać dodany później/)).toHaveTextContent(
      "W v1.3.0 nie ma pliku docs/gone.md. Mógł zostać dodany później, przeniesiony lub usunięty.",
    );
    expect(screen.getByRole("heading", { name: "Podobne ścieżki w v1.3.0" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pokaż katalog główny v1.3.0" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Otwórz tę ścieżkę w v1.4.0" })).toBeInTheDocument();
  });

  it("shows the version picker in Polish", async () => {
    show(() => (
      <VersionPicker
        owner="acme"
        repo="payments"
        versions={versions}
        current={versions[0] as Version}
        pinned={false}
        keep={{}}
      />
    ));
    await userEvent.click(
      await screen.findByRole("button", { name: "Wersja: v1.4.0. Zmień wersję" }),
    );
    const list = screen.getByRole("list", { name: "Wersje" });
    expect(within(list).getByRole("link", { name: /v1\.4\.0/ })).toHaveTextContent("domyślna");
    expect(within(list).getByRole("link", { name: /main/ })).toHaveTextContent("gałąź");
    expect(screen.getByRole("button", { name: "Przypnij v1.4.0 jako domyślną" })).toBeVisible();
    const filter = screen.getByRole("searchbox", { name: "Filtruj wersje" });
    expect(filter).toHaveAttribute("placeholder", "Filtruj 8 wersji");
    await userEvent.type(filter, "zzz");
    expect(screen.getByText("Żadna wersja nie pasuje do „zzz”.")).toBeInTheDocument();
  });

  it("shows the file tree's own rows in Polish", async () => {
    const rows = buildRows(
      [{ path: "docs/start.md", title: "Getting started", tags: [], size: 10 }],
      new Set(["docs", "guide"]),
      new Set([""]),
      new Set(),
      new Set(["guide"]),
    );
    show(() => (
      <FileTree
        owner="acme"
        repo="payments"
        version="v1.4.0"
        tags={undefined}
        selected={undefined}
        rows={rows}
        scopeState={() => "idle"}
        label="Pliki wersji v1.4.0"
        onToggle={vi.fn()}
        onMore={vi.fn()}
        onOpen={vi.fn()}
      />
    ));
    expect(await screen.findByRole("treeitem", { name: "Pokaż więcej plików" })).toBeVisible();
    expect(screen.getByRole("treeitem", { name: /Getting started/ })).toHaveTextContent(
      "Plik start.md",
    );
  });

  it("says a library is not found in Polish", async () => {
    show(() => <LibraryNotFound owner="acme" repo="nope" />);
    expect(
      await screen.findByRole("heading", { name: "Nie znaleziono biblioteki" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/ExactDocs nie ma biblioteki/)).toHaveTextContent(
      "ExactDocs nie ma biblioteki /acme/nope. Sprawdź adres albo wybierz bibliotekę z listy.",
    );
    expect(screen.getByRole("link", { name: "Wszystkie biblioteki" })).toBeInTheDocument();
  });

  it("says a removed tag stays when the import gives it too, in Polish", () => {
    const kept = { tag_origins: [{ tag: "guide", origins: ["path_rule" as const] }] };
    expect(keptNotice(kept, "guide", "pl")).toBe(
      "guide pozostaje przy tym artykule: nadaje go również import.",
    );
    expect(keptNotice(kept, "guide", "en")).toBe(
      "guide stays on this article: its import gives it too.",
    );
  });
});
