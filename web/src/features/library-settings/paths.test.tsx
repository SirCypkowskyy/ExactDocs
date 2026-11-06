import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { TestRouter } from "@/shared/lib/test-router";
import { LibrarySettingsPage } from "./index";
import {
  draftOf,
  explainSettings,
  reprocessWarning,
  savedHeadline,
  selectionChange,
  settingsOf,
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

function serve(put?: (body: Record<string, unknown>) => Reply) {
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
    expect(tags.what).toMatch(/^Its version \(v1\.2\.0\) will be re-processed/);
    expect(tags.what).toMatch(/nothing is fetched/);
    const many = reprocessWarning("paths", ["a", "b", "c", "d", "e", "f", "g"]);
    expect(many.what).toMatch(/a, b, c, d, e, and 2 more/);
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
      reprocess: null,
      job_id: null,
      versions: ["v1"],
    };
    expect(savedHeadline(saved)).toMatch(/Nothing changed/);
    expect(savedHeadline({ ...saved, versions: [] })).toMatch(/no version yet/);
    expect(savedHeadline({ ...saved, reprocess: "tags", job_id: "j" })).toMatch(/re-tagged/);
    expect(savedHeadline({ ...saved, reprocess: "paths", job_id: "j" })).toMatch(/re-processed/);
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
});
