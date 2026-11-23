import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { AddLibraryPage, JobLine, JobsPage, LibrariesPage } from "./index";
import {
  explainAddError,
  explainPreviewError,
  previewCountText,
  summarizeProblems,
  validateUrl,
} from "./model/add-library";

const SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678";

const library = {
  id: "/acme/payments",
  title: "Payments",
  description: "",
  default_version: "v1.4.0",
  default_pinned: false,
  source_url: "https://github.com/acme/payments.git",
  version_count: 2,
  refs: ["v1.4.0", "main"].map((ref) => ({
    ref,
    kind: ref === "main" ? "branch" : "tag",
    commit_sha: SHA,
    imported_at: "2026-11-01T10:00:00Z",
    is_default: ref === "v1.4.0",
  })),
  tags: ["api"],
  last_imported_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
};

const job = (over: Record<string, unknown> = {}) => ({
  id: "j1",
  kind: "import",
  library: "/acme/payments",
  version: "v1.4.0",
  commit_sha: SHA,
  state: "succeeded",
  done: 4,
  total: 4,
  skipped: 2,
  problems: [],
  error: null,
  error_code: null,
  created_at: "2026-11-01T10:00:00Z",
  started_at: "2026-11-01T10:00:01Z",
  finished_at: "2026-11-01T10:01:00Z",
  cancelled_by: null,
  cancelled_at: null,
  cancellable: false,
  ...over,
});

function serve(reply: (url: string) => unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = reply(url);
      return body === undefined ? new Response("{}", { status: 404 }) : Response.json(body);
    }),
  );
}

function renderWith(children: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>);
}

beforeEach(() => setPreferences({ language: "pl" }));
afterEach(() => {
  resetPreferences();
  vi.unstubAllGlobals();
});

describe("the libraries slice in Polish", () => {
  it("lists libraries with Polish counts, labels, dates and sync status", async () => {
    serve((url) => {
      if (url.includes("/v1/libraries?")) {
        return { libraries: [library], next_cursor: null, total: 1 };
      }
      if (url.endsWith("/v1/jobs/latest")) return { jobs: [job()] };
      return undefined;
    });
    renderWith(<TestRouter pages={{ "/": LibrariesPage }} />);

    const table = await screen.findByRole("table", { name: "Biblioteki" });
    const row = (await within(table).findByRole("link", { name: "Payments" })).closest("tr");
    if (!row) throw new Error("no row");
    expect(screen.getByRole("heading", { name: "Biblioteki" })).toBeInTheDocument();
    expect(screen.getByText("1 biblioteka")).toHaveAttribute("role", "status");
    expect(screen.getByLabelText("Znajdź bibliotekę")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dodaj bibliotekę" })).toBeInTheDocument();
    for (const header of ["Wersja domyślna", "Wersje", "Ostatni import", "Synchronizacja"]) {
      expect(
        within(table).getByRole("columnheader", { name: new RegExp(header) }),
      ).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Ostatni import" })).toBeInTheDocument();
    expect(within(row).getByText("3 dni temu")).toBeInTheDocument();
    expect(await within(row).findByText("Zsynchronizowano, pominięto 2")).toBeInTheDocument();
    expect(screen.getByText("1–1 z 1")).toBeInTheDocument();
    await userEvent.click(
      within(row).getByRole("button", { name: "Więcej opcji: /acme/payments" }),
    );
    const menu = await screen.findByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Synchronizuj teraz" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "Pokaż jej zadania" })).toBeInTheDocument();
  });

  it("walks the add form in Polish, with Polish refusals", async () => {
    serve((url) =>
      url.endsWith("/v1/repositories/check")
        ? { host: "github", library_id: "/acme/payments", default_branch: "main" }
        : undefined,
    );
    renderWith(<TestRouter pages={{ "/libraries/new": AddLibraryPage }} start="/libraries/new" />);

    expect(
      await screen.findByRole("heading", { level: 1, name: "Dodaj bibliotekę" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Sprawdzenie repozytorium").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Sprawdź repozytorium" }));
    expect(await screen.findByText("Wklej adres repozytorium git.")).toBeInTheDocument();

    await userEvent.type(
      screen.getByLabelText("Adres repozytorium"),
      "https://github.com/acme/payments",
    );
    await userEvent.click(screen.getByRole("button", { name: "Sprawdź repozytorium" }));
    expect(
      await screen.findByText("Znaleziono na GitHubie. Domyślna gałąź to main."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Identyfikator biblioteki")).toHaveValue("/acme/payments");
    expect(screen.getByRole("button", { name: "Dodaj bibliotekę" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Anuluj" })).toBeInTheDocument();
  });

  it("names jobs, their states and kinds in Polish", async () => {
    serve((url) =>
      url.includes("/v1/jobs?")
        ? {
            jobs: [
              job({ id: "j1" }),
              job({ id: "j2", state: "failed", kind: "reprocess", version: null }),
            ],
            next_cursor: null,
            total: 2,
          }
        : undefined,
    );
    renderWith(<TestRouter pages={{ "/jobs": JobsPage }} start="/jobs" />);

    expect(await screen.findByRole("heading", { name: "Zadania" })).toBeInTheDocument();
    expect(await screen.findByText("2 zadania")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: /Stan/ })).toBeInTheDocument();
    expect(within(table).getByText("nieudane")).toBeInTheDocument();
    expect(within(table).getByText("ponowne przetwarzanie")).toBeInTheDocument();
    expect(within(table).getByText("wszystkie")).toBeInTheDocument();
    // The pagination bar speaks Polish too.
    const pages = screen.getByRole("navigation", { name: "Stronicowanie" });
    expect(within(pages).getByText("1–2 z 2")).toBeInTheDocument();
    expect(within(pages).getByText("Strona 1 z 1")).toBeInTheDocument();
    expect(within(pages).getByLabelText("Wierszy na stronie")).toHaveValue("20");
    expect(within(pages).getByRole("button", { name: "Następna strona" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Stan" }));
    expect(await screen.findByRole("option", { name: "w toku" })).toBeInTheDocument();
  });

  it("follows an import in Polish", async () => {
    serve(() => job({ kind: "import", state: "running", done: 2, total: 5, finished_at: null }));
    renderWith(<JobLine jobId="j1" label="v1.4.0" />);

    expect(await screen.findByText("2 z 5 plików")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Postęp importu v1.4.0" })).toBeInTheDocument();
  });

  it("explains refusals and counts with Polish plurals outside React", () => {
    expect(validateUrl("", "pl")).toBe("Wklej adres repozytorium git.");
    const busy = (retry?: number) =>
      new HttpError(429, "/v1/x", { error: "preview_busy", detail: "d", fields: [] }, retry);
    expect(explainPreviewError(busy(2), null, undefined, "pl").message).toMatch(/za 2 sekundy\.$/);
    expect(explainAddError(busy(5), null, undefined, "pl").message).toMatch(/za 5 sekund\.$/);
    expect(previewCountText({ total: 1, truncated: false, files: ["a.md"] }, "pl")).toBe(
      "1 plik pasuje.",
    );
    expect(previewCountText({ total: 3, truncated: false, files: [] }, "pl")).toBe(
      "3 pliki pasują.",
    );
    const many = Array.from({ length: 1000 }, (_, i) => `${i}.md`);
    expect(previewCountText({ total: 4213, truncated: true, files: many }, "pl")).toBe(
      "4213 plików pasuje. Wyświetlono pierwszych 1000.",
    );
    // The current language is the default.
    expect(
      summarizeProblems([{ path: "a.bin", code: "binary", reason: "r", is_skip: true }])
        .skipGroups[0]?.label,
    ).toBe("Pliki binarne");
  });
});
