import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { LibrarySettingsPage } from "./index";
import {
  draftOf,
  effectiveChange,
  explainSettings,
  reprocessWarning,
  savedHeadline,
  selectionChange,
  settingsOf,
  unhealedJob,
} from "./model/settings";

const SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678";
const version = (ref: string, kind: string, is_default = false) => ({
  ref,
  kind,
  commit_sha: SHA,
  imported_at: "2026-11-01T10:00:00Z",
  is_default,
});
const library = {
  id: "/acme/payments",
  title: "Payments",
  description: "Card payments.",
  source_url: "https://github.com/acme/payments",
  host: "github",
  default_branch: "main",
  settings: {
    include_paths: ["docs/"],
    exclude_paths: [],
    tag_rules: [{ pattern: "docs/api/**", tag: "api" }],
    chunking: {},
  },
  default_version: "v1.2.0",
  versions: [version("v1.2.0", "tag", true), version("main", "branch")],
};

type Reply = { status: number; body: unknown };

interface Extra {
  /** The library's jobs, newest first (`GET …/jobs`). */
  jobs?: unknown[];
  private?: boolean;
}

const reprocessJob = (over: Record<string, unknown> = {}) => ({
  id: "f1",
  kind: "reprocess",
  library: "/acme/payments",
  version: null,
  commit_sha: null,
  state: "failed",
  done: 2,
  total: 2,
  problems: [],
  error: "2 version(s) could not be re-processed",
  error_code: "no_articles",
  created_at: "2026-11-01T10:00:00Z",
  started_at: "2026-11-01T10:00:01Z",
  finished_at: "2026-11-01T10:01:00Z",
  ...over,
});

function serve(put?: (body: Record<string, unknown>) => Reply, extra: Extra = {}) {
  const sent: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT" && url.endsWith("/v1/libraries/acme/payments/settings")) {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        sent.push(body);
        const r = put?.(body) ?? {
          status: 202,
          body: {
            library_id: "/acme/payments",
            ...body,
            reprocess: "paths",
            job_id: "r1",
            versions: ["v1.2.0", "main"],
          },
        };
        return Response.json(r.body, { status: r.status });
      }
      if (url.includes("/v1/repositories/refs")) {
        return Response.json({ default_branch: "main", branches: [], tags: [], truncated: false });
      }
      if (url.includes("/v1/libraries/acme/payments/jobs")) {
        return Response.json({ jobs: extra.jobs ?? [], next_cursor: null });
      }
      if (url.endsWith("/v1/libraries/acme/payments/access")) {
        return Response.json({ private: extra.private ?? false });
      }
      return new Response("{}", { status: 404 });
    }),
  );
  return sent;
}

const jobs = {
  Import: () => null,
  Line: ({ jobId, label }: { jobId: string; label: string }) => (
    <p>
      job {jobId} for {label}
    </p>
  ),
  Preview: (p: { version: string | null; include: string; exclude: string }) => (
    <p data-testid="preview">
      preview {p.version} [{p.include}] [{p.exclude}]
    </p>
  ),
};

function renderPage(lib: unknown = library) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <TestRouter
        pages={{
          "/": () => <p>Libraries home</p>,
          "/libraries/$owner/$repo": () => <p>Browse</p>,
          "/libraries/$owner/$repo/settings": () => (
            <LibrarySettingsPage owner="acme" repo="payments" library={lib as never} jobs={jobs} />
          ),
        }}
        start="/libraries/acme/payments/settings"
      />
    </QueryClientProvider>,
  );
}

const section = async () => within(await screen.findByRole("region", { name: "Files and tags" }));
const saveButton = () => screen.getByRole("button", { name: "Save paths and tags" });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("paths and tag rules model", () => {
  const stored = library.settings;

  it("fills the form from what is stored and sends the whole set back", () => {
    const draft = draftOf(stored);
    expect(draft).toEqual({
      include: "docs/",
      exclude: "",
      rules: [{ key: 0, pattern: "docs/api/**", tag: "api" }],
    });
    expect(
      settingsOf({
        include: " docs/ \n\n",
        exclude: "docs/archive/**",
        rules: [...draft.rules, { key: 1, pattern: "", tag: " " }],
      }),
    ).toEqual({
      include_paths: ["docs/"],
      exclude_paths: ["docs/archive/**"],
      tag_rules: [{ pattern: "docs/api/**", tag: "api" }],
    });
  });

  it("tells a path change from a tag-only change, and sees no change in case or blank lines", () => {
    const draft = draftOf(stored);
    expect(selectionChange(stored, { ...draft, include: "docs/\n\n " })).toBeNull();
    expect(
      selectionChange(stored, {
        ...draft,
        rules: [{ key: 0, pattern: "docs/api/** ", tag: "API" }],
      }),
    ).toBeNull();
    expect(selectionChange(stored, { ...draft, exclude: "docs/archive/**" })).toBe("paths");
    expect(selectionChange(stored, { ...draft, include: "" })).toBe("paths");
    expect(selectionChange(stored, { ...draft, rules: [] })).toBe("tags");
    expect(
      selectionChange(stored, {
        exclude: "x/**",
        include: "docs/",
        rules: [],
      }),
    ).toBe("paths");
  });

  it("warns that every version is re-processed, naming them", () => {
    const paths = reprocessWarning("paths", ["v1.2.0", "main"]);
    expect(paths.title).toBe("Re-process every version?");
    expect(paths.what).toMatch(
      /^Every version will be re-processed: all 2 of them \(v1\.2\.0, main\)/,
    );
    expect(paths.what).toMatch(/fetched again at the commit it serves/);
    expect(paths.safe).toMatch(/keeps serving what it has now/);
    const tags = reprocessWarning("tags", ["v1.2.0"]);
    expect(tags.title).toBe("Re-tag every version?");
    expect(tags.what).toMatch(/^Its version \(v1\.2\.0\) will be re-tagged/);
    expect(tags.what).not.toMatch(/re-processed/);
    const rerun = reprocessWarning("paths", ["v1.2.0"], true);
    expect(rerun.what).toMatch(/last re-processing failed, so this runs it in full/);
    expect(tags.what).toMatch(/nothing is fetched/);
    const many = reprocessWarning("paths", ["a", "b", "c", "d", "e", "f", "g"]);
    expect(many.what).toMatch(/a, b, c, d, e, and 2 more/);
  });

  it("warns a tag-only change as a full re-process while the last re-process failed", () => {
    const failed = { kind: "reprocess", state: "failed" } as const;
    expect(effectiveChange("tags", null)).toEqual({ change: "tags", afterFailure: false });
    expect(effectiveChange("tags", [failed])).toEqual({ change: "paths", afterFailure: true });
    expect(effectiveChange("tags", [{ ...failed, kind: "retag" }])).toEqual({
      change: "tags",
      afterFailure: false,
    });
    expect(effectiveChange("tags", [{ ...failed, state: "succeeded" }]).change).toBe("tags");
  });

  it("keeps a failed re-process pending after a narrower job succeeded, as the server does", () => {
    const failed = { kind: "reprocess", state: "failed" } as const;
    const retagged = { kind: "retag", state: "succeeded" } as const;
    const rechunked = { kind: "rechunk", state: "succeeded" } as const;
    // Newest first: the re-tag after the failed re-process did not re-import anything.
    expect(effectiveChange("tags", [retagged, failed])).toEqual({
      change: "paths",
      afterFailure: true,
    });
    expect(effectiveChange("tags", [rechunked, failed]).change).toBe("paths");
    expect(unhealedJob([retagged, failed])).toBe(failed);
    // A re-process that did not fail since redoes it; one still queued will too.
    const redone = { kind: "reprocess", state: "succeeded" } as const;
    expect(effectiveChange("tags", [retagged, redone, failed]).change).toBe("tags");
    expect(effectiveChange("tags", [{ kind: "reprocess", state: "queued" }, failed]).change).toBe(
      "tags",
    );
    // The widest failure wins, whichever is newer.
    const retagFailed = { kind: "retag", state: "failed" } as const;
    expect(unhealedJob([retagFailed, failed])).toBe(failed);
    // Other jobs (imports) neither fail nor redo a re-processing.
    expect(effectiveChange("tags", [{ kind: "import", state: "succeeded" }, failed]).change).toBe(
      "paths",
    );
  });

  it("warns a tag-only change as a re-chunk while the last re-chunk failed", () => {
    const failed = { kind: "rechunk", state: "failed" } as const;
    expect(effectiveChange("tags", [failed])).toEqual({ change: "chunking", afterFailure: true });
    // A paths edit re-processes in full anyway: it is not worded as a re-run of the re-chunk.
    expect(effectiveChange("paths", [failed])).toEqual({ change: "paths", afterFailure: false });
    expect(effectiveChange("paths", [{ kind: "reprocess", state: "failed" }])).toEqual({
      change: "paths",
      afterFailure: true,
    });
    expect(effectiveChange("tags", [{ kind: "retag", state: "succeeded" }, failed]).change).toBe(
      "chunking",
    );
    const warning = reprocessWarning("chunking", ["v1.2.0"], true);
    expect(warning.title).toBe("Re-chunk every version?");
    expect(warning.what).toMatch(/^Its version \(v1\.2\.0\) will be re-chunked/);
    expect(warning.what).toMatch(/nothing is fetched/);
    expect(warning.confirm).toBe("Save and re-chunk");
  });

  it("leaves the chunking out of what is saved, so the server keeps it", () => {
    const sent = settingsOf({ include: "docs/", exclude: "", rules: [] });
    expect(sent).not.toHaveProperty("chunking");
  });

  it("maps refusals to the field they are about", () => {
    const e = (status: number, code: string) =>
      new HttpError(status, "/v1/x", { error: code, detail: "d", fields: [] });
    expect(explainSettings(e(422, "invalid_path_pattern")).field).toBe("paths");
    expect(explainSettings(e(422, "invalid_tag")).field).toBe("tags");
    expect(explainSettings(e(404, "not_found")).message).toMatch(/no longer exists/);
    expect(explainSettings(e(401, "unauthenticated")).link?.href).toBe("/sign-in");
    expect(explainSettings(new TypeError("offline")).message).toMatch(/Can't reach/);
  });

  it("headlines what saving did", () => {
    const saved = {
      library_id: "/acme/payments",
      include_paths: [],
      exclude_paths: [],
      tag_rules: [],
      chunking: { split_level: 6, min_chars: 0, max_chars: null, chunker: "markdown" as const },
      reprocess: null,
      job_id: null,
      versions: ["v1"],
    };
    expect(savedHeadline(saved)).toMatch(/Nothing changed/);
    expect(savedHeadline({ ...saved, versions: [] })).toMatch(/no version yet/);
    expect(savedHeadline({ ...saved, reprocess: "tags", job_id: "j" })).toMatch(/re-tagged/);
    expect(savedHeadline({ ...saved, reprocess: "paths", job_id: "j" })).toMatch(/re-processed/);
    expect(savedHeadline({ ...saved, reprocess: "chunking", job_id: "j" })).toMatch(/re-chunked/);
  });
});

describe("editing paths and tag rules", () => {
  it("warns that every version is re-processed, then starts the job and shows its progress", async () => {
    const sent = serve();
    renderPage();
    const s = await section();
    await userEvent.type(s.getByLabelText("Leave out"), "docs/archive/**");
    await userEvent.click(saveButton());

    const dialog = await screen.findByRole("alertdialog", { name: "Re-process every version?" });
    expect(dialog).toHaveTextContent("Every version will be re-processed");
    expect(dialog).toHaveTextContent("v1.2.0, main");
    expect(sent).toHaveLength(0);

    await userEvent.click(within(dialog).getByRole("button", { name: "Save and re-process" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(sent).toEqual([
      {
        include_paths: ["docs/"],
        exclude_paths: ["docs/archive/**"],
        tag_rules: [{ pattern: "docs/api/**", tag: "api" }],
      },
    ]);
    expect(s.getByText("Saved. Every version is being re-processed.")).toBeInTheDocument();
    expect(s.getByText("job r1 for every version")).toBeInTheDocument();
    // The form now shows what is stored: nothing left to save.
    expect(s.getByText("Nothing changed yet.")).toBeInTheDocument();
    await waitFor(() => expect(document.getElementById("paths-status")).toHaveFocus());
  });

  it("sends nothing when the warning is cancelled, and returns focus to Save", async () => {
    const sent = serve();
    renderPage();
    const s = await section();
    await userEvent.type(s.getByLabelText("Leave out"), "docs/archive/**");
    await userEvent.click(saveButton());
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(saveButton()).toHaveFocus());
    expect(sent).toHaveLength(0);
    expect(s.getByLabelText("Leave out")).toHaveValue("docs/archive/**");
  });

  it("says a tag-only change re-tags every version without fetching", async () => {
    const sent = serve((body) => ({
      status: 202,
      body: {
        library_id: "/acme/payments",
        ...body,
        reprocess: "tags",
        job_id: "t1",
        versions: ["v1.2.0", "main"],
      },
    }));
    renderPage();
    const s = await section();
    await userEvent.click(s.getByRole("button", { name: "Add a tag rule" }));
    await userEvent.type(s.getByLabelText("Path for tag rule 2"), "docs/guide/**");
    await userEvent.type(s.getByLabelText("Tag for rule 2"), "Guide Docs");
    await userEvent.click(saveButton());
    const dialog = await screen.findByRole("alertdialog", { name: "Re-tag every version?" });
    expect(dialog).toHaveTextContent("nothing is fetched");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save and re-tag" }));
    expect(await s.findByText("Saved. Every version is being re-tagged.")).toBeInTheDocument();
    expect(sent[0]?.tag_rules).toEqual([
      { pattern: "docs/api/**", tag: "api" },
      { pattern: "docs/guide/**", tag: "Guide Docs" },
    ]);
  });

  it("does not send an unchanged form", async () => {
    const sent = serve();
    renderPage();
    await section();
    await userEvent.click(saveButton());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(sent).toHaveLength(0);
  });

  it("keeps a bad path or rule local, next to its field", async () => {
    const sent = serve();
    renderPage();
    const s = await section();
    await userEvent.type(s.getByLabelText("Leave out"), "../outside");
    await userEvent.click(saveButton());
    expect(await s.findByText(/uses “\.\.”/)).toBeInTheDocument();
    expect(s.getByLabelText("Leave out")).toHaveAttribute("aria-invalid", "true");
    await userEvent.clear(s.getByLabelText("Leave out"));
    await userEvent.clear(s.getByLabelText("Tag for rule 1"));
    await userEvent.type(s.getByLabelText("Tag for rule 1"), "#api");
    await userEvent.click(saveButton());
    await waitFor(() => expect(s.getByLabelText("Path for tag rule 1")).toHaveFocus());
    expect(s.getByLabelText("Tag for rule 1")).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(sent).toHaveLength(0);
  });

  it("puts a server refusal next to the paths and focuses them", async () => {
    serve(() => ({
      status: 422,
      body: { error: "invalid_path_pattern", detail: "bad", fields: [] },
    }));
    renderPage();
    const s = await section();
    await userEvent.type(s.getByLabelText("Leave out"), "docs/[[");
    await userEvent.click(saveButton());
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Save and re-process",
      }),
    );
    expect(await s.findByText(/One of the paths isn't valid/)).toBeInTheDocument();
    await waitFor(() => expect(s.getByLabelText("Only these paths")).toHaveFocus());
    expect(s.getByLabelText("Leave out")).toHaveValue("docs/[");
  });

  it("saves without a warning while the library has no version", async () => {
    const sent = serve((body) => ({
      status: 200,
      body: { library_id: "/acme/payments", ...body, reprocess: null, job_id: null, versions: [] },
    }));
    renderPage({ ...library, versions: [], default_version: null });
    const s = await section();
    expect(s.getByText(/Nothing changed yet/)).toBeInTheDocument();
    await userEvent.type(s.getByLabelText("Leave out"), "docs/archive/**");
    expect(s.getByText(/No version is imported yet/)).toBeInTheDocument();
    await userEvent.click(saveButton());
    expect(
      await s.findByText(/versions imported from now on use these settings/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(sent).toHaveLength(1);
  });

  it("previews the paths as typed in the default version", async () => {
    serve();
    renderPage();
    const s = await section();
    await userEvent.type(s.getByLabelText("Leave out"), "docs/archive/**");
    expect(s.getByTestId("preview")).toHaveTextContent("preview v1.2.0 [docs/] [docs/archive/**]");
  });

  it("runs a failed re-processing again with the stored settings, without asking", async () => {
    const sent = serve(
      (body) => ({
        status: 202,
        body: {
          library_id: "/acme/payments",
          ...body,
          reprocess: "paths",
          job_id: "r2",
          versions: ["v1.2.0", "main"],
        },
      }),
      {
        jobs: [{ ...reprocessJob(), kind: "import", id: "i9", state: "succeeded" }, reprocessJob()],
      },
    );
    renderPage();
    const s = await section();
    expect(await s.findByText(/The last re-processing failed/)).toBeInTheDocument();
    expect(s.getByText("job f1 for every version")).toBeInTheDocument();
    // An unsaved edit is not what runs again: the stored settings are.
    await userEvent.type(s.getByLabelText("Leave out"), "docs/new/**");
    await userEvent.click(s.getByRole("button", { name: /Run again/ }));
    expect(await s.findByText("job r2 for every version")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(sent).toEqual([
      {
        include_paths: ["docs/"],
        exclude_paths: [],
        tag_rules: [{ pattern: "docs/api/**", tag: "api" }],
      },
    ]);
    await waitFor(() => expect(document.getElementById("paths-status")).toHaveFocus());
  });

  it("offers nothing to run again after a re-processing that succeeded", async () => {
    serve(undefined, { jobs: [reprocessJob({ state: "succeeded" })] });
    renderPage();
    const s = await section();
    await waitFor(() =>
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/jobs?"),
        expect.anything(),
      ),
    );
    expect(s.queryByRole("button", { name: /Run again/ })).not.toBeInTheDocument();
  });

  it("warns that a tag-only change runs the failed re-processing in full", async () => {
    serve(undefined, { jobs: [reprocessJob()] });
    renderPage();
    const s = await section();
    await s.findByText(/The last re-processing failed/);
    await userEvent.clear(s.getByLabelText("Tag for rule 1"));
    await userEvent.type(s.getByLabelText("Tag for rule 1"), "reference");
    await userEvent.click(saveButton());
    const dialog = await screen.findByRole("alertdialog", { name: "Re-process every version?" });
    expect(dialog).toHaveTextContent("runs it in full");
    expect(dialog).not.toHaveTextContent("nothing is fetched");
  });

  it("warns about the failed re-processing, not the re-tag that succeeded after it", async () => {
    serve(undefined, {
      jobs: [reprocessJob({ id: "t1", kind: "retag", state: "succeeded" }), reprocessJob()],
    });
    renderPage();
    const s = await section();
    // The re-tag did not redo it, so the failed re-processing is still offered again.
    expect(await s.findByText(/The last re-processing failed/)).toBeInTheDocument();
    expect(s.getByText("job f1 for every version")).toBeInTheDocument();
    await userEvent.clear(s.getByLabelText("Tag for rule 1"));
    await userEvent.type(s.getByLabelText("Tag for rule 1"), "reference");
    await userEvent.click(saveButton());
    const dialog = await screen.findByRole("alertdialog", { name: "Re-process every version?" });
    expect(dialog).toHaveTextContent("runs it in full");
    expect(dialog).not.toHaveTextContent("nothing is fetched");
  });

  it("does not call a paths edit after a failed re-chunk a re-run of a failed re-processing", async () => {
    serve(undefined, { jobs: [reprocessJob({ kind: "rechunk" })] });
    renderPage();
    const s = await section();
    expect(await s.findByText(/The last re-chunking failed/)).toBeInTheDocument();
    await userEvent.type(s.getByLabelText("Leave out"), "docs/archive/**");
    await userEvent.click(saveButton());
    const dialog = await screen.findByRole("alertdialog", { name: "Re-process every version?" });
    expect(dialog).not.toHaveTextContent("last re-processing failed");
    expect(dialog).toHaveTextContent("imported with the new paths");
  });

  it("explains that a private library cannot be previewed, instead of offering a preview", async () => {
    serve(undefined, { private: true });
    renderPage();
    const s = await section();
    expect(
      await s.findByText(/Preview isn't available for a private repository yet/),
    ).toBeInTheDocument();
    expect(s.queryByTestId("preview")).not.toBeInTheDocument();
  });
});

describe("in Polish", () => {
  afterEach(() => resetPreferences());

  it("warns before re-processing and reports the save in Polish", async () => {
    setPreferences({ language: "pl" });
    serve();
    renderPage();
    const s = within(await screen.findByRole("region", { name: "Pliki i tagi" }));
    expect(s.getByText("Nic jeszcze nie zmieniono.")).toBeInTheDocument();
    await userEvent.type(document.getElementById("exclude") as HTMLElement, "docs/archive/**");
    expect(
      s.getByText(
        "Pojawi się prośba o potwierdzenie: każda wersja zostanie przetworzona ponownie.",
      ),
    ).toBeInTheDocument();
    await userEvent.click(s.getByRole("button", { name: "Zapisz ścieżki i tagi" }));

    const dialog = await screen.findByRole("alertdialog", {
      name: "Przetworzyć ponownie każdą wersję?",
    });
    expect(dialog).toHaveTextContent(
      "Każda wersja zostanie ponownie przetworzona, łącznie 2 (v1.2.0, main).",
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Zapisz i przetwórz ponownie" }),
    );
    expect(
      await s.findByText("Zapisano. Każda wersja jest ponownie przetwarzana."),
    ).toBeInTheDocument();
    expect(s.getByText("job r1 for wszystkie wersje")).toBeInTheDocument();
  });

  it("offers to run a failed re-processing again, in Polish", async () => {
    setPreferences({ language: "pl" });
    serve(undefined, { jobs: [reprocessJob({ kind: "retag" })] });
    renderPage();
    const s = within(await screen.findByRole("region", { name: "Pliki i tagi" }));
    expect(
      await s.findByText(
        "Ostatnie ponowne tagowanie nie powiodło się. Każda wersja nadal udostępnia to, co dotąd.",
      ),
    ).toBeInTheDocument();
    expect(
      s.getByRole("button", {
        name: /^Uruchom ponownie\s*tagowanie z zapisanymi ścieżkami i regułami tagów$/,
      }),
    ).toBeInTheDocument();
    expect(reprocessWarning("tags", ["a", "b", "c", "d", "e", "f", "g"], false, "pl").what).toMatch(
      /^Każda wersja zostanie ponownie otagowana, łącznie 7 \(a, b, c, d, e i jeszcze 2\)\. /,
    );
  });
});
