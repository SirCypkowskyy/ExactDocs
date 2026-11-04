import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { TestRouter } from "@/shared/lib/test-router";
import { AddLibraryPage, LibrariesPage } from "./index";
import {
  explainAddError,
  explainCheckError,
  summarizeProblems,
  validateLibraryId,
  validatePatterns,
  validateRule,
  validateUrl,
} from "./model/add-library";

const SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678";
const URL_ = "https://github.com/acme/payments";
const err = (status: number, code: string, detail = "x") => ({
  status,
  body: { error: code, detail, fields: [] },
});

interface Routes {
  check?: () => { status: number; body: unknown };
  refs?: () => { status: number; body: unknown };
  create?: (body: Record<string, unknown>) => { status: number; body: unknown };
  job?: () => unknown;
}

const REFS = {
  default_branch: "main",
  branches: [
    { name: "main", commit_sha: SHA },
    { name: "next", commit_sha: SHA },
  ],
  tags: [
    { name: "v1.4.0", commit_sha: SHA },
    { name: "v1.3.0", commit_sha: SHA },
  ],
  truncated: false,
};
const job = (over: Record<string, unknown> = {}) => ({
  id: "j1",
  kind: "import",
  library: "/acme/payments",
  version: "main",
  commit_sha: SHA,
  state: "succeeded",
  done: 4,
  total: 4,
  problems: [],
  error: null,
  created_at: "2026-11-01T10:00:00Z",
  started_at: "2026-11-01T10:00:01Z",
  finished_at: "2026-11-01T10:01:00Z",
  ...over,
});

function serve(routes: Routes = {}) {
  const create = vi.fn((body: Record<string, unknown>) =>
    routes.create
      ? routes.create(body)
      : {
          status: 201,
          body: {
            library_id: "/acme/payments",
            ref: "main",
            ref_kind: "branch",
            commit_sha: SHA,
            job_id: "j1",
          },
        },
  );
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const reply = (r: { status: number; body: unknown }) =>
      Response.json(r.body, { status: r.status });
    if (url.endsWith("/v1/repositories/check")) {
      return reply(
        routes.check?.() ?? {
          status: 200,
          body: { host: "github", library_id: "/acme/payments", default_branch: "main" },
        },
      );
    }
    if (url.includes("/v1/repositories/refs"))
      return reply(routes.refs?.() ?? { status: 200, body: REFS });
    if (url.endsWith("/v1/libraries") && init?.method === "POST") {
      return reply(create(JSON.parse(String(init.body))));
    }
    if (url.includes("/v1/jobs/j1")) return Response.json(routes.job?.() ?? job());
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, create };
}

function renderAdd() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <TestRouter
        pages={{ "/": () => <p>Libraries home</p>, "/libraries/new": AddLibraryPage }}
        start="/libraries/new"
      />
    </QueryClientProvider>,
  );
  return queryClient;
}

async function checkRepo(url = URL_) {
  await userEvent.type(await screen.findByLabelText("Repository address"), url);
  await userEvent.click(screen.getByRole("button", { name: "Check repository" }));
}

describe("add library model", () => {
  it("validates addresses, ids, paths and tag rules", () => {
    expect(validateUrl("")).toMatch(/Paste/);
    expect(validateUrl("github.com/acme/x")).toMatch(/Start with/);
    expect(validateUrl("https://user:pw@github.com/a/b")).toMatch(/username/);
    expect(validateUrl("git@github.com:acme/x.git")).toBeUndefined();
    expect(validateUrl(URL_)).toBeUndefined();
    expect(validateLibraryId("acme/x")).toBeDefined();
    expect(validateLibraryId("/acme/x")).toBeUndefined();
    expect(validatePatterns("docs/\n/etc/passwd")).toMatch(/starts with/);
    expect(validatePatterns("docs/../x")).toMatch(/\.\./);
    expect(validatePatterns("docs/\n**/*.mdx")).toBeUndefined();
    expect(validateRule({ key: 0, pattern: "docs/**", tag: "API" }).tag).toBeDefined();
    expect(validateRule({ key: 0, pattern: "docs/**", tag: "api" })).toEqual({});
  });

  it("maps every failure to words and a place", () => {
    const e = (status: number, code: string) =>
      new HttpError(status, "/v1/x", { error: code, detail: "d", fields: [] });
    expect(explainCheckError(e(422, "invalid_repository_url")).field).toBe("url");
    expect(explainCheckError(e(422, "repository_unreachable")).message).toMatch(/Couldn't reach/);
    expect(explainCheckError(e(422, "not_a_git_repository")).field).toBe("url");
    expect(explainCheckError(e(401, "unauthenticated")).link?.href).toBe("/sign-in");
    expect(explainCheckError(e(403, "setup_required")).link?.href).toBe("/setup");
    expect(explainCheckError(new TypeError("offline")).message).toMatch(/Can't reach the server/);
    expect(explainAddError(e(409, "library_id_taken"), null).field).toBe("id");
    expect(explainAddError(e(422, "unknown_ref"), "v9").message).toMatch(/v9/);
    expect(explainAddError(e(422, "ambiguous_ref"), "abc1234").field).toBe("ref");
    expect(explainAddError(e(422, "invalid_path_pattern"), null).field).toBe("paths");
    expect(explainAddError(e(422, "invalid_tag"), null).field).toBe("tags");
    expect(explainAddError(e(403, "forbidden"), null).message).toMatch(/isn't allowed/);
  });

  it("groups skipped files by reason and keeps notes and the truncation marker apart", () => {
    const p = (path: string, code: string, is_skip: boolean) =>
      ({ path, code, reason: `r ${code}`, is_skip }) as never;
    const s = summarizeProblems([
      p("a.md", "binary", true),
      p("b.md", "binary", true),
      p("c.md", "too_large", true),
      p("d.md", "front_matter", false),
      p("", "truncated", false),
      p("e.md", "brand_new_code", true),
    ]);
    expect(s.skipped).toBe(4);
    expect(s.skipGroups.map((g) => [g.code, g.files.length, g.known])).toEqual([
      ["binary", 2, true],
      ["too_large", 1, true],
      ["brand_new_code", 1, false],
    ]);
    expect(s.notes.map((n) => n.path)).toEqual(["d.md"]);
    expect(s.truncated).toBe(true);
  });
});

describe("add library flow", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("checks the address, proposes an id, offers refs, and sends the whole selection", async () => {
    const { create } = serve();
    renderAdd();
    await checkRepo();

    expect(
      await screen.findByText(/Found on GitHub\. Default branch is main\./),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Library ID")).toHaveValue("/acme/payments");
    const picker = await screen.findByLabelText("Version to import");
    expect(
      within(picker).getByRole("option", { name: "Default branch (main)" }),
    ).toBeInTheDocument();
    expect(
      within(picker)
        .getAllByRole("group")
        .map((g) => g.getAttribute("label")),
    ).toEqual(["Branches (2)", "Tags (2)"]);
    await userEvent.selectOptions(picker, "tag:v1.4.0");

    await userEvent.click(screen.getByText("Choose files and tags"));
    await userEvent.type(screen.getByLabelText("Only these paths"), "docs/");
    await userEvent.type(screen.getByLabelText("Leave out"), "docs/internal/**");
    await userEvent.click(screen.getByRole("button", { name: "Add a tag rule" }));
    await userEvent.type(screen.getByLabelText("Path for tag rule 1"), "docs/api/**");
    await userEvent.type(screen.getByLabelText("Tag for rule 1"), "api");
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));

    await screen.findByRole("heading", { name: /^Imported \// });
    expect(create).toHaveBeenCalledWith({
      url: URL_,
      library_id: "/acme/payments",
      ref: "v1.4.0",
      include_paths: ["docs/"],
      exclude_paths: ["docs/internal/**"],
      tag_rules: [{ pattern: "docs/api/**", tag: "api" }],
    });
  });

  it("sends no ref for the default branch", async () => {
    const { create } = serve();
    renderAdd();
    await checkRepo();
    await screen.findByLabelText("Version to import");
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    await screen.findByRole("heading", { name: /^Imported \// });
    expect(create.mock.calls[0]?.[0]).not.toHaveProperty("ref");
  });

  it("tells the user when branches and tags were cut", async () => {
    serve({ refs: () => ({ status: 200, body: { ...REFS, truncated: true } }) });
    renderAdd();
    await checkRepo();
    expect(
      await screen.findByText(/Only the first 1000 branches and 1000 tags are listed/),
    ).toBeInTheDocument();
  });

  it("filters a long ref list and lets the user type any ref", async () => {
    const many = Array.from({ length: 30 }, (_, i) => ({ name: `v1.${i}.0`, commit_sha: SHA }));
    const { create } = serve({ refs: () => ({ status: 200, body: { ...REFS, tags: many } }) });
    renderAdd();
    await checkRepo();
    await userEvent.type(await screen.findByLabelText("Filter branches and tags"), "v1.2");
    const picker = screen.getByLabelText("Version to import");
    expect(within(picker).getAllByRole("option").length).toBeLessThan(20);
    await userEvent.selectOptions(picker, "other");
    await userEvent.type(screen.getByPlaceholderText(/commit SHA/), "abc1234");
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    await waitFor(() => expect(create.mock.calls[0]?.[0]).toMatchObject({ ref: "abc1234" }));
  });

  it.each([
    [
      "invalid URL (server)",
      err(422, "invalid_repository_url"),
      /doesn't look like a git repository address/,
    ],
    ["unreachable", err(422, "repository_unreachable", "boom"), /Couldn't reach that address/],
    ["no repository", err(422, "not_a_git_repository"), /No git repository there/],
    ["login required", err(422, "repository_auth_required"), /asks for a login/],
  ])("explains a failed check: %s", async (_name, reply, text) => {
    serve({ check: () => reply });
    renderAdd();
    await checkRepo();
    const input = screen.getByLabelText("Repository address");
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "true");
    await waitFor(() => expect(input).toHaveFocus());
    expect(input).toHaveAccessibleDescription(text);
    // No empty alert bar, and no form below yet.
    expect(screen.getByRole("alert").textContent).toBe("");
    expect(screen.queryByLabelText("Library ID")).not.toBeInTheDocument();
  });

  it("rejects a malformed address before asking the server", async () => {
    const { fetchMock } = serve();
    renderAdd();
    await checkRepo("not a url");
    expect(await screen.findByText(/no spaces/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends a signed-out user to sign in", async () => {
    serve({ check: () => err(401, "unauthenticated") });
    renderAdd();
    await checkRepo();
    const alert = await screen.findByRole("alert");
    await waitFor(() => expect(alert).toHaveTextContent("Your session ended."));
    expect(within(alert).getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/sign-in",
    );
  });

  it("explains a forbidden account", async () => {
    serve({ check: () => err(403, "forbidden") });
    renderAdd();
    await checkRepo();
    expect(await screen.findByRole("alert")).toHaveTextContent("isn't allowed to add libraries");
  });

  it("starts over when the address changes after a check", async () => {
    serve();
    renderAdd();
    await checkRepo();
    await screen.findByLabelText("Library ID");
    await userEvent.type(screen.getByLabelText("Repository address"), "x");
    expect(screen.queryByLabelText("Library ID")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check repository" })).toBeInTheDocument();
  });

  it.each([
    ["id taken", err(409, "library_id_taken"), "Library ID", /already used/],
    ["unknown ref", err(422, "unknown_ref"), "Version to import", /no default branch/],
    [
      "ambiguous ref",
      err(422, "ambiguous_ref"),
      "Version to import",
      /starts more than one commit/,
    ],
    ["bad path", err(422, "invalid_path_pattern"), "Only these paths", /One of the paths/],
  ])("puts a refused add next to its field: %s", async (_name, reply, label, text) => {
    serve({ create: () => reply });
    renderAdd();
    await checkRepo();
    await screen.findByLabelText("Version to import");
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.getByLabelText(label)).toHaveAttribute("aria-invalid", "true");
    await waitFor(() => expect(screen.getByLabelText(label)).toHaveFocus());
    // The form is still there to correct and resubmit.
    expect(screen.getByRole("button", { name: "Add library" })).toBeInTheDocument();
  });

  it("checks local fields before sending and opens the section that holds the mistake", async () => {
    const { create } = serve();
    renderAdd();
    await checkRepo();
    await screen.findByLabelText("Version to import");
    await userEvent.clear(screen.getByLabelText("Library ID"));
    await userEvent.type(screen.getByLabelText("Library ID"), "payments");
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    expect(await screen.findByText(/Use the form \/owner\/repo/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Library ID")).toHaveFocus());

    await userEvent.type(screen.getByLabelText("Library ID"), "/x");
    await userEvent.click(screen.getByText("Choose files and tags"));
    await userEvent.type(screen.getByLabelText("Only these paths"), "/abs");
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    expect(await screen.findByText(/starts with \//)).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });

  it("shows a bad tag rule only after a submit attempt", async () => {
    serve();
    renderAdd();
    await checkRepo();
    await screen.findByLabelText("Version to import");
    await userEvent.click(screen.getByText("Choose files and tags"));
    await userEvent.click(screen.getByRole("button", { name: "Add a tag rule" }));
    await userEvent.type(screen.getByLabelText("Path for tag rule 1"), "docs/**");
    await userEvent.type(screen.getByLabelText("Tag for rule 1"), "Bad Tag");
    expect(screen.queryByText(/lower-case letters/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    expect(await screen.findByText(/lower-case letters/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Tag for rule 1")).toHaveFocus());
  });

  it("watches the import, announces phases not counts, then lists skipped files by reason", async () => {
    let state = job({ state: "running", done: 1, total: 4 });
    serve({ job: () => state });
    renderAdd();
    await checkRepo();
    await screen.findByLabelText("Version to import");
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));

    const bar = await screen.findByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "1");
    expect(bar).toHaveAttribute("aria-valuemax", "4");
    expect(screen.getByText("1 of 4 files")).toBeInTheDocument();
    const live = screen
      .getByRole("heading", { name: /Importing/ })
      .parentElement?.querySelector("[role=status]");
    await waitFor(() => expect(live).toHaveTextContent("Importing."));

    state = job({
      done: 4,
      total: 4,
      problems: [
        { path: "docs/logo.md", code: "binary", reason: "has NUL bytes", is_skip: true },
        { path: "docs/huge.md", code: "too_large", reason: "3 MiB", is_skip: true },
        { path: "docs/odd.md", code: "front_matter", reason: "bad tags", is_skip: false },
        { path: "", code: "truncated", reason: "more", is_skip: false },
      ],
    });
    await screen.findByRole("heading", { name: /^Imported \// }, { timeout: 4000 });
    expect(live).toHaveTextContent("Import finished. 4 files imported, 2+ skipped.");
    expect(screen.getByRole("heading", { name: /Skipped files \(2\+\)/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Binary files/ })).toBeInTheDocument();
    expect(screen.getByText("docs/huge.md")).toBeInTheDocument();
    expect(screen.getByText(/Showing the first 2 skipped files/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Imported with a note/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to libraries" })).toHaveAttribute("href", "/");
  }, 10_000);

  it("shows a failed import with its reason and no skipped section", async () => {
    serve({
      job: () => job({ state: "failed", done: 2, total: 4, error: "git fetch failed: HTTP 403" }),
    });
    renderAdd();
    await checkRepo();
    await screen.findByLabelText("Version to import");
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    expect(await screen.findByRole("heading", { name: /Import failed/ })).toBeInTheDocument();
    expect(screen.getByText("git fetch failed: HTTP 403")).toBeInTheDocument();
    expect(screen.getByText("Details from the server")).toBeInTheDocument();
    expect(screen.getByText(/sync it again from the libraries page/)).toBeInTheDocument();
    // "Add another" would walk straight into library_id_taken.
    expect(screen.queryByRole("button", { name: "Add another" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to libraries" })).toBeInTheDocument();
    expect(screen.getByText("Stopped after 2 of 4 files")).toBeInTheDocument();
    expect(screen.queryByText(/Skipped files/)).not.toBeInTheDocument();
  });

  it("starts over for another library", async () => {
    serve();
    renderAdd();
    await checkRepo();
    await screen.findByLabelText("Version to import");
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add another" }));
    expect(await screen.findByLabelText("Repository address")).toHaveValue("");
  });
});

async function addDefault() {
  await checkRepo();
  await screen.findByLabelText("Version to import");
  await userEvent.click(screen.getByRole("button", { name: "Add library" }));
}

describe("add library flow, review fixes", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends a ref typed after the refs request failed", async () => {
    const { create } = serve({ refs: () => err(500, "boom") });
    renderAdd();
    await checkRepo();
    const typed = await screen.findByLabelText("Branch, tag or commit", {}, { timeout: 6000 });
    await userEvent.type(typed, "v1.2.0");
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    await waitFor(() => expect(create.mock.calls[0]?.[0]).toMatchObject({ ref: "v1.2.0" }));
  }, 10_000);

  it("focuses the typed ref when the server refuses it", async () => {
    serve({ refs: () => err(500, "boom"), create: () => err(422, "unknown_ref") });
    renderAdd();
    await checkRepo();
    await userEvent.type(
      await screen.findByLabelText("Branch, tag or commit", {}, { timeout: 6000 }),
      "nope",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    await waitFor(() => expect(screen.getByLabelText("Branch, tag or commit")).toHaveFocus());
    expect(screen.getByLabelText("Branch, tag or commit")).toHaveAccessibleDescription(
      /no branch, tag or commit/,
    );
  }, 10_000);

  it("names the typed-ref input and moves focus to it", async () => {
    serve();
    renderAdd();
    await checkRepo();
    await userEvent.selectOptions(await screen.findByLabelText("Version to import"), "other");
    await waitFor(() => expect(screen.getByLabelText("Branch, tag or commit")).toHaveFocus());
  });

  it("does not submit when Enter is pressed in the ref filter, and selects a single match", async () => {
    const many = Array.from({ length: 30 }, (_, i) => ({ name: `v1.${i}.0`, commit_sha: SHA }));
    const { create } = serve({ refs: () => ({ status: 200, body: { ...REFS, tags: many } }) });
    renderAdd();
    await checkRepo();
    const filter = await screen.findByLabelText("Filter branches and tags");
    await userEvent.type(filter, "v1.2");
    expect(screen.getByText(/\d+ of 32 match/)).toBeInTheDocument();
    await userEvent.type(filter, "7.0{Enter}");
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Version to import")).toHaveValue("tag:v1.27.0");
  });

  it("refreshes the library list and the job feed once the import is over", async () => {
    serve();
    const qc = renderAdd();
    const spy = vi.spyOn(qc, "invalidateQueries");
    await addDefault();
    await screen.findByRole("heading", { name: /^Imported \// });
    const keys = spy.mock.calls.map(([f]) => JSON.stringify(f?.queryKey));
    expect(keys.filter((k) => k === '["libraries","list"]').length).toBeGreaterThanOrEqual(2);
    expect(keys.filter((k) => k === '["libraries","latest-jobs"]').length).toBeGreaterThanOrEqual(
      2,
    );
    expect(keys).not.toContain('["libraries"]');
  });

  it("sends one request for two submits in the same tick", async () => {
    const { create } = serve();
    renderAdd();
    await checkRepo();
    await screen.findByLabelText("Version to import");
    const form = screen
      .getByRole("button", { name: "Add library" })
      .closest("form") as HTMLFormElement;
    fireEvent.submit(form);
    fireEvent.submit(form);
    await screen.findByRole("heading", { name: /^Imported \// });
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("lets the user re-check right after editing the address of a slow check", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => {
      release = r;
    });
    let first = true;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/v1/repositories/check")) {
        if (first) {
          first = false;
          await gate;
        }
        return Response.json({ host: "github", library_id: "/acme/other", default_branch: "main" });
      }
      return Response.json(REFS);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAdd();
    await checkRepo();
    expect(screen.getByRole("button", { name: "Checking" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await userEvent.type(screen.getByLabelText("Repository address"), "2");
    const button = screen.getByRole("button", { name: "Check repository" });
    expect(button).toHaveAttribute("aria-disabled", "false");
    await userEvent.click(button);
    expect(await screen.findByLabelText("Library ID")).toHaveValue("/acme/other");
    release();
    // The stale answer must not overwrite the newer one.
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByLabelText("Library ID")).toHaveValue("/acme/other");
  });

  it("forgets an old refusal when the address changes", async () => {
    serve({ create: () => err(409, "library_id_taken") });
    renderAdd();
    await addDefault();
    await screen.findByText(/already used/);
    await userEvent.type(screen.getByLabelText("Repository address"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Check repository" }));
    await screen.findByLabelText("Library ID");
    expect(screen.queryByText(/already used/)).not.toBeInTheDocument();
  });

  it("rejects an address over 2048 characters before asking", async () => {
    const { fetchMock } = serve();
    renderAdd();
    await userEvent.click(await screen.findByLabelText("Repository address"));
    await userEvent.paste(`https://github.com/${"a".repeat(2100)}`);
    await userEvent.click(screen.getByRole("button", { name: "Check repository" }));
    expect(await screen.findByText(/too long/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not blame the server for a refused form", async () => {
    serve({ create: () => err(422, "something_new") });
    renderAdd();
    await addDefault();
    expect(await screen.findByRole("alert")).toHaveTextContent("Check the form and try again");
  });

  it("puts a no_articles refusal at the paths and opens them", async () => {
    serve({ create: () => err(422, "no_articles") });
    renderAdd();
    await addDefault();
    const box = await screen.findByLabelText("Only these paths");
    await waitFor(() => expect(box).toHaveFocus());
    expect(box).toHaveAccessibleDescription(/No Markdown files match/);
  });

  it("gives each path box its own message", async () => {
    serve();
    renderAdd();
    await checkRepo();
    await screen.findByLabelText("Version to import");
    await userEvent.click(screen.getByText("Choose files and tags"));
    await userEvent.type(screen.getByLabelText("Leave out"), "../secrets");
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    const exclude = await screen.findByLabelText("Leave out");
    expect(exclude).toHaveAttribute("aria-invalid", "true");
    expect(exclude).toHaveAccessibleDescription(/uses “\.\.”/);
    expect(screen.getByLabelText("Only these paths")).not.toHaveAttribute("aria-invalid");
  });

  it("focuses an invalid tag refused by the server", async () => {
    serve({ create: () => err(422, "invalid_tag") });
    renderAdd();
    await addDefault();
    expect(await screen.findByText(/A tag isn't valid/)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add a tag rule" })).toHaveFocus(),
    );
  });

  it("stops polling when the job is gone and says so", async () => {
    const { fetchMock } = serve();
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.includes("/v1/jobs/j1"))
        return Response.json(err(404, "unknown_job").body, { status: 404 });
      if (url.endsWith("/v1/repositories/check"))
        return Response.json({
          host: "github",
          library_id: "/acme/payments",
          default_branch: "main",
        });
      if (url.includes("/v1/repositories/refs")) return Response.json(REFS);
      if (init?.method === "POST")
        return Response.json(
          {
            library_id: "/acme/payments",
            ref: "main",
            ref_kind: "branch",
            commit_sha: SHA,
            job_id: "j1",
          },
          { status: 201 },
        );
      return new Response("{}", { status: 404 });
    });
    renderAdd();
    await addDefault();
    expect(await screen.findByText(/can't find this import any more/)).toBeInTheDocument();
    const calls = () =>
      fetchMock.mock.calls.filter(([u]) => String(u).includes("/v1/jobs/")).length;
    const seen = calls();
    await new Promise((r) => setTimeout(r, 1800));
    expect(calls()).toBe(seen);
  }, 10_000);

  it("keeps polling through a network failure and says contact was lost", async () => {
    const { fetchMock } = serve();
    const original = fetchMock.getMockImplementation();
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.includes("/v1/jobs/j1")) throw new TypeError("offline");
      return original?.(url, init) as Promise<Response>;
    });
    renderAdd();
    await addDefault();
    expect(
      await screen.findByText("Lost contact, retrying…", {}, { timeout: 4000 }),
    ).toBeInTheDocument();
  }, 10_000);

  it("stops polling once the import has finished", async () => {
    const { fetchMock } = serve();
    renderAdd();
    await addDefault();
    await screen.findByRole("heading", { name: /^Imported \// });
    const calls = () =>
      fetchMock.mock.calls.filter(([u]) => String(u).includes("/v1/jobs/")).length;
    const seen = calls();
    await new Promise((r) => setTimeout(r, 1800));
    expect(calls()).toBe(seen);
  }, 10_000);

  it("shows an unknown skip code with the server's own sentence", async () => {
    serve({
      job: () =>
        job({
          problems: [
            {
              path: "docs/x.md",
              code: "brand_new",
              reason: "Something we have no word for",
              is_skip: true,
            },
          ],
        }),
    });
    renderAdd();
    await addDefault();
    expect(await screen.findByText("Something we have no word for")).toBeInTheDocument();
  });

  it("says 30+ skipped files fold away and count honestly", async () => {
    const problems = Array.from({ length: 40 }, (_, i) => ({
      path: `docs/b${i}.md`,
      code: "binary",
      reason: "x",
      is_skip: true,
    }));
    serve({ job: () => job({ problems }) });
    renderAdd();
    await addDefault();
    expect(await screen.findByText(/Skipped files/, { selector: "summary" })).toBeInTheDocument();
    expect(screen.getAllByText("(40)").length).toBeGreaterThan(0);
  });
});

describe("entry points", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("links to the add screen from the header and from the empty state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("/v1/libraries")
          ? Response.json({ libraries: [], next_cursor: null })
          : Response.json({ jobs: [] }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TestRouter pages={{ "/": LibrariesPage, "/libraries/new": () => <p>Add page</p> }} />
      </QueryClientProvider>,
    );
    const links = await screen.findAllByRole("link", { name: "Add library" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/libraries/new");
  });
});
