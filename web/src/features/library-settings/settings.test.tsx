import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { BROWSE_KEY, LIBRARIES_KEY } from "@/shared/lib/query-keys";
import { TestRouter } from "@/shared/lib/test-router";
import { LibrarySettingsPage, LibrarySettingsSkeleton } from "./index";
import {
  changedFields,
  explainAddVersion,
  explainReimport,
  explainRemove,
  explainSync,
  failureWords,
  statusWords,
  syncHeadline,
  validateDetails,
} from "./model/settings";

const SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678";
const SHA2 = "ffffffffffffffffffffffffffffffffffffffff";
const library = {
  id: "/acme/payments",
  title: "Payments",
  description: "Card payments.",
  source_url: "https://github.com/acme/payments",
  host: "github",
  default_branch: "main",
  settings: { include_paths: [], exclude_paths: [], tag_rules: [], chunking: {} },
  default_version: "v1.2.0",
  versions: [
    {
      ref: "v1.2.0",
      kind: "tag",
      commit_sha: SHA,
      imported_at: "2026-11-01T10:00:00Z",
      is_default: true,
    },
    {
      ref: "main",
      kind: "branch",
      commit_sha: SHA,
      imported_at: "2026-11-01T10:00:00Z",
      is_default: false,
    },
  ],
};
const REFS = {
  default_branch: "main",
  branches: [
    { name: "main", commit_sha: SHA },
    { name: "next", commit_sha: SHA },
  ],
  tags: [
    { name: "v1.3.0", commit_sha: SHA },
    { name: "v1.2.0", commit_sha: SHA },
  ],
  truncated: false,
};
const failure = (status: number, error: string, detail = "server words") => ({
  status,
  body: { error, detail, fields: [], close_matches: [] },
});

type Reply = { status: number; body: unknown };
interface Routes {
  patch?: (body: Record<string, unknown>) => Reply;
  addVersion?: (body: Record<string, unknown>) => Reply;
  sync?: () => Reply;
  reimport?: (body: Record<string, unknown>) => Reply;
  removeVersion?: (ref: string) => Reply;
  removeLibrary?: () => Reply;
  /** Held until released: lets a test act while a DELETE is in flight. */
  gate?: Promise<unknown>;
  /** The library has a stored token or key. */
  private?: boolean;
  refs?: () => Reply;
}

function serve(routes: Routes = {}) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url, body });
      const reply = (r: Reply) => Response.json(r.body, { status: r.status });
      if (url.includes("/v1/repositories/refs")) {
        return reply(routes.refs?.() ?? { status: 200, body: REFS });
      }
      if (url.endsWith("/access") && routes.private !== undefined) {
        return Response.json({ private: routes.private });
      }
      if (method === "GET" && url.includes("/versions?")) {
        return Response.json({
          library: library.id,
          versions: library.versions,
          next_cursor: null,
          total: library.versions.length,
        });
      }
      if (method === "PATCH") {
        return reply(routes.patch?.(body) ?? { status: 200, body: { ...library, ...body } });
      }
      if (method === "POST" && url.endsWith("/versions")) {
        return reply(
          routes.addVersion?.(body) ?? {
            status: 202,
            body: {
              library_id: "/acme/payments",
              ref: body.ref,
              ref_kind: "tag",
              commit_sha: SHA,
              job_id: "j9",
            },
          },
        );
      }
      if (method === "POST" && url.endsWith("/versions/reimport")) {
        return reply(
          routes.reimport?.(body) ?? {
            status: 202,
            body: {
              library_id: "/acme/payments",
              ref: body.ref,
              ref_kind: "tag",
              previous_commit_sha: SHA,
              commit_sha: SHA2,
              job_id: "j11",
            },
          },
        );
      }
      if (method === "POST" && url.endsWith("/sync")) {
        return reply(
          routes.sync?.() ?? { status: 200, body: { library_id: "/acme/payments", versions: [] } },
        );
      }
      if (method === "DELETE") await routes.gate;
      if (method === "DELETE" && url.includes("/versions/")) {
        const ref = decodeURIComponent(url.split("/versions/")[1] ?? "");
        return reply(
          routes.removeVersion?.(ref) ?? {
            status: 200,
            body: {
              library: "/acme/payments",
              ref,
              default_version: "main",
              collection_job_id: "c1",
            },
          },
        );
      }
      if (method === "DELETE") {
        return reply(
          routes.removeLibrary?.() ?? {
            status: 200,
            body: {
              library: "/acme/payments",
              ref: null,
              default_version: null,
              collection_job_id: null,
            },
          },
        );
      }
      return new Response("{}", { status: 404 });
    }),
  );
  return calls;
}

const jobs = {
  Import: ({ added, finish }: { added: { ref: string }; finish: React.ReactNode }) => (
    <div>
      <p>Importing {added.ref}</p>
      {finish}
    </div>
  ),
  Line: ({ jobId, label }: { jobId: string; label: string }) => (
    <p>
      job {jobId} for {label}
    </p>
  ),
  Preview: () => null,
};

function renderPage(lib: object = library, start = "/libraries/acme/payments/settings") {
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
        start={start}
      />
    </QueryClientProvider>,
  );
  return queryClient;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

/** Opens a version's row menu and asks to remove it. */
async function removeFromMenu(ref: string) {
  await userEvent.click(await screen.findByRole("button", { name: `More actions for ${ref}` }));
  await userEvent.click(await screen.findByRole("menuitem", { name: "Remove version…" }));
}

describe("settings model", () => {
  it("validates the title and the description", () => {
    expect(validateDetails({ title: "  ", description: "" }).title).toMatch(/Give/);
    expect(validateDetails({ title: "x".repeat(201), description: "" }).title).toMatch(/200/);
    expect(validateDetails({ title: "ok", description: "y".repeat(1001) }).description).toMatch(
      /1000/,
    );
    expect(validateDetails({ title: "ok", description: "" })).toEqual({
      title: undefined,
      description: undefined,
    });
  });

  it("sends only what changed", () => {
    const saved = { title: "A", description: "B" };
    expect(changedFields(saved, { title: " A ", description: "B" })).toEqual({});
    expect(changedFields(saved, { title: "C", description: "B" })).toEqual({ title: "C" });
    expect(changedFields(saved, { title: "A", description: "" })).toEqual({ description: "" });
  });

  it("maps every refusal to words", () => {
    const e = (status: number, code: string) =>
      new HttpError(status, "/v1/x", { error: code, detail: "d", fields: [] });
    expect(explainAddVersion(e(409, "version_exists"), "v1").field).toBe("ref");
    expect(explainAddVersion(e(409, "version_importing"), "v1").message).toMatch(/being imported/);
    expect(explainAddVersion(e(409, "commit_already_imported"), "v1").message).toBe(
      "d, so a second version would hold the same text.",
    );
    expect(explainAddVersion(e(409, "version_exists"), "v1").jump?.href).toBe("#sync-heading");
    expect(explainAddVersion(e(422, "unknown_ref"), "v9").message).toMatch(
      /no branch, tag or commit/,
    );
    expect(explainAddVersion(e(422, "ambiguous_ref"), "ab").message).toMatch(/more than one/);
    expect(explainAddVersion(e(404, "not_found"), "v1").message).toMatch(/no longer exists/);
    expect(explainAddVersion(e(401, "x"), "v1").link?.href).toBe("/sign-in");
    expect(explainAddVersion(new TypeError("net"), "v1").message).toMatch(/Can't reach/);
    expect(explainSync(e(409, "version_importing")).message).toMatch(/still importing/);
    expect(explainSync(e(409, "version_importing")).tone).toBe("info");
    expect(explainSync(e(422, "repo_unreachable")).tone).toBeUndefined();
    expect(explainSync(e(422, "repo_unreachable")).message).toMatch(/couldn't be read/);
    expect(explainSync(e(422, "auth_failed")).message).toMatch(/refused or can't be read/);
    expect(explainSync(e(422, "auth_failed")).message).toMatch(/send the token or key again/);
    expect(explainSync(e(422, "host_key_changed")).message).toMatch(/SSH host key .* changed/);
    expect(explainSync(e(422, "host_key_changed")).message).not.toMatch(/deleted/);
    expect(explainReimport(e(422, "not_a_tag")).message).toMatch(/branch is updated with Re-sync/);
    expect(explainReimport(e(422, "host_key_changed")).message).toMatch(/SSH host key/);
    expect(explainReimport(e(422, "repository_unreachable")).message).toMatch(/couldn't be read/);
    expect(explainReimport(e(409, "version_importing")).final).toBeFalsy();
    expect(explainRemove(e(409, "import_in_progress"), "version v1").message).toMatch(
      /never cancels/,
    );
  });

  it("explains a failed version without guessing when its code is unknown", () => {
    const v = (error_code: string | null) =>
      ({ ref: "main", ref_kind: "branch", status: "failed", error_code }) as never;
    expect(failureWords(v("ref_deleted"))).toMatch(/branch is gone/);
    expect(failureWords(v("tag_moved"))).toMatch(/unless you confirm it/);
    expect(failureWords(v(null))).toMatch(/^It could not be synced\./);
    expect(failureWords(v("something_new"))).not.toMatch(/queued/);
  });

  it("headlines a re-sync", () => {
    const v = (status: string) => ({ ref: "r", status }) as never;
    expect(syncHeadline({ library_id: "x", versions: [v("queued"), v("queued")] })).toBe(
      "2 versions are updating.",
    );
    expect(syncHeadline({ library_id: "x", versions: [v("up_to_date"), v("pinned")] })).toBe(
      "Everything is up to date.",
    );
    expect(syncHeadline({ library_id: "x", versions: [v("failed")] })).toMatch(
      /could not be checked/,
    );
  });
});

describe("sharing section", () => {
  it("links to the sharing page and, next to it, the access log", async () => {
    serve();
    renderPage();
    const section = within(await screen.findByRole("region", { name: "Sharing" }));
    expect(section.getByRole("link", { name: "Manage sharing" })).toHaveAttribute(
      "href",
      "/libraries/acme/payments/sharing",
    );
    expect(section.getByRole("link", { name: "Access log" })).toHaveAttribute(
      "href",
      "/libraries/acme/payments/access-log",
    );
    expect(screen.getAllByRole("link", { name: "Access log" })).toHaveLength(1);
  });
});

describe("header", () => {
  it("names the library with its logo beside the title", async () => {
    serve();
    renderPage({ ...library, logo: "0123456789abcdef" });
    const header = (await screen.findByRole("heading", { level: 1 })).closest("header");
    expect(header?.querySelector("img")).toHaveAttribute(
      "src",
      "/api/v1/libraries/acme/payments/logo?v=0123456789abcdef",
    );
    expect(screen.getByRole("navigation", { name: "Breadcrumb" }).querySelector("img")).toBeNull();
  });
});

describe("details form", () => {
  it("says so beside the nav while edits are unsaved, and toasts once saved", async () => {
    const success = vi.spyOn(toast, "success").mockReturnValue("t");
    serve();
    renderPage();
    const title = await screen.findByLabelText("Title");
    await userEvent.type(title, "!");
    expect(await screen.findByText("1 section has unsaved changes.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(success).toHaveBeenCalledWith("Saved the library details"));
    success.mockRestore();
  });

  it("saves a changed title and sends nothing else", async () => {
    const calls = serve();
    renderPage();
    const title = await screen.findByLabelText("Title");
    await userEvent.clear(title);
    await userEvent.type(title, "Payments SDK");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ title: "Payments SDK" }),
    );
  });

  it("does not send an untouched form or an empty title", async () => {
    const calls = serve();
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Save changes" }));
    await userEvent.clear(screen.getByLabelText("Title"));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Give the library a title.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("puts a server refusal next to the field", async () => {
    serve({
      patch: () => ({
        status: 422,
        body: {
          error: "validation_error",
          detail: "x",
          fields: [{ loc: ["body", "title"], msg: "Title must be one line", type: "value_error" }],
          close_matches: [],
        },
      }),
    });
    renderPage();
    const title = await screen.findByLabelText("Title");
    await userEvent.type(title, "!");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Title must be one line")).toBeInTheDocument();
    expect(title).toHaveFocus();
  });
});

describe("adding a version", () => {
  async function open() {
    await userEvent.click(await screen.findByRole("button", { name: "Add a version" }));
    return screen.findByLabelText("Version to import");
  }

  it("adds a picked tag and shows its import", async () => {
    const calls = serve();
    renderPage();
    const picker = await open();
    await userEvent.selectOptions(picker, "tag:v1.3.0");
    await userEvent.click(screen.getByRole("button", { name: "Add version" }));
    expect(await screen.findByText("Importing v1.3.0")).toBeInTheDocument();
    expect(calls.find((c) => c.url.endsWith("/versions") && c.method === "POST")?.body).toEqual({
      ref: "v1.3.0",
    });
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    // The card stays until its row has collapsed.
    await waitFor(() => expect(screen.queryByText("Importing v1.3.0")).not.toBeInTheDocument());
  });

  it("asks for a choice, offers only versions not yet imported, and sends nothing until then", async () => {
    const calls = serve();
    renderPage();
    const picker = await open();
    const options = within(picker)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toContain("Choose a branch or tag…");
    expect(options).not.toContain("main");
    expect(options).not.toContain("v1.2.0");
    expect(options.some((o) => o?.startsWith("Default branch"))).toBe(false);
    expect(options).toEqual(expect.arrayContaining(["next", "v1.3.0"]));
    await userEvent.click(screen.getByRole("button", { name: "Add version" }));
    expect(await screen.findByText(/Choose a branch or tag from the list/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/versions"))).toBe(false);
  });

  it("links a refused existing version to the re-sync section", async () => {
    serve({ addVersion: () => failure(409, "version_exists") });
    renderPage();
    await userEvent.selectOptions(await open(), "tag:v1.3.0");
    await userEvent.click(screen.getByRole("button", { name: "Add version" }));
    const link = await screen.findByRole("link", { name: /Branches can be updated with Re-sync/ });
    expect(link).toHaveAttribute("href", "#sync-heading");
  });

  it.each([
    ["version_exists", 409, /already a version/],
    ["version_importing", 409, /being imported right now/],
    ["commit_already_imported", 409, /so a second version would hold the same text/],
    ["unknown_ref", 422, /no branch, tag or commit/],
  ])("explains %s next to the picker", async (code, status, text) => {
    serve({ addVersion: () => failure(status, code) });
    renderPage();
    const picker = await open();
    await userEvent.selectOptions(picker, "tag:v1.3.0");
    await userEvent.click(screen.getByRole("button", { name: "Add version" }));
    expect(await screen.findByText(text)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Version to import")).toHaveFocus());
  });

  /**
   * Holds animation frames until `run()`, so a focus request made a frame late can never land
   * before the test has checked focus and moved it elsewhere.
   */
  function holdFrames() {
    const held: FrameRequestCallback[] = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => held.push(cb));
    return {
      run: () => {
        for (const cb of held.splice(0)) cb(performance.now());
      },
    };
  }

  it("does not pull focus away once the refusal is on screen", async () => {
    const frames = holdFrames();
    serve({ addVersion: () => failure(422, "unknown_ref") });
    renderPage();
    await userEvent.selectOptions(await open(), "tag:v1.3.0");
    await userEvent.click(screen.getByRole("button", { name: "Add version" }));
    await screen.findByText(/no branch, tag or commit/);
    // Focus is where the refusal points as soon as the user can see it, not a frame later.
    expect(screen.getByLabelText("Version to import")).toHaveFocus();
    const elsewhere = screen.getByRole("button", { name: "Cancel" });
    elsewhere.focus();
    frames.run();
    expect(elsewhere).toHaveFocus();
  });

  it("does not pull focus away once the missing choice is on screen", async () => {
    const frames = holdFrames();
    serve();
    renderPage();
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Add version" }));
    await screen.findByText(/Choose a branch or tag from the list/);
    expect(screen.getByLabelText("Version to import")).toHaveFocus();
    const elsewhere = screen.getByRole("button", { name: "Cancel" });
    elsewhere.focus();
    frames.run();
    expect(elsewhere).toHaveFocus();
  });

  it("focuses the typed ref as it appears and leaves focus alone after", async () => {
    const frames = holdFrames();
    serve();
    renderPage();
    await userEvent.selectOptions(await open(), "other");
    expect(screen.getByLabelText("Branch, tag or commit")).toHaveFocus();
    const elsewhere = screen.getByRole("button", { name: "Cancel" });
    elsewhere.focus();
    frames.run();
    expect(elsewhere).toHaveFocus();
  });

  it("returns focus to the add button on cancel, and leaves it alone after", async () => {
    const frames = holdFrames();
    serve();
    renderPage();
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Add a version" })).toHaveFocus();
    const elsewhere = screen.getByRole("button", { name: "Re-sync now" });
    elsewhere.focus();
    frames.run();
    expect(elsewhere).toHaveFocus();
  });

  it("keeps a typed ref when the list of branches cannot load", async () => {
    const calls = serve();
    const real = globalThis.fetch;
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) =>
      String(url).includes("/repositories/refs")
        ? Promise.resolve(new Response("{}", { status: 500 }))
        : real(url, init),
    );
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add a version" }));
    await userEvent.type(await screen.findByLabelText("Branch, tag or commit"), "v2.0.0");
    await userEvent.click(screen.getByRole("button", { name: "Add version" }));
    await screen.findByText("Importing v2.0.0");
    expect(
      calls.some(
        (c) => c.url.endsWith("/versions") && (c.body as { ref: string }).ref === "v2.0.0",
      ),
    ).toBe(true);
  });
});

describe("re-sync", () => {
  const synced = (versions: unknown[], status = 202) => ({
    status,
    body: { library_id: "/acme/payments", versions },
  });
  const v = (over: Record<string, unknown>) => ({
    ref: "main",
    ref_kind: "branch",
    status: "queued",
    previous_commit_sha: SHA,
    commit_sha: SHA2,
    job_id: "j5",
    ...over,
  });

  it("shows each version's outcome and the job of a queued one", async () => {
    serve({
      sync: () =>
        synced([v({}), v({ ref: "v1.2.0", ref_kind: "tag", status: "pinned", job_id: null })]),
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Re-sync now" }));
    expect(await screen.findByText("1 version is updating.")).toBeInTheDocument();
    expect(screen.getByText("job j5 for main")).toBeInTheDocument();
    expect(screen.getByText("v1.2.0 is pinned and never changes.")).toBeInTheDocument();
    expect(screen.queryByText("Pinned")).not.toBeInTheDocument();
  });

  it("says so when nothing moved", async () => {
    serve({ sync: () => synced([v({ status: "up_to_date", job_id: null })], 200) });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Re-sync now" }));
    expect(await screen.findByText("Everything is up to date.")).toBeInTheDocument();
  });

  it("explains a branch that is gone", async () => {
    serve({ sync: () => synced([v({ status: "failed", error_code: "ref_deleted" })]) });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Re-sync now" }));
    expect(await screen.findByText(/branch is gone from the repository/)).toBeInTheDocument();
  });

  const moved = {
    ref: "v1.4.0",
    ref_kind: "tag",
    status: "failed",
    commit_sha: SHA,
    job_id: "f1",
    error_code: "tag_moved",
  };

  it("explains a tag that moved, and that it is re-imported only when confirmed", async () => {
    const calls = serve({ sync: () => synced([v(moved)], 200) });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Re-sync now" }));
    expect(await screen.findByText(/tag now points at another commit/)).toBeInTheDocument();
    expect(screen.getByText(/not re-imported unless you confirm it/)).toBeInTheDocument();
    expect(screen.getByText("v1.4.0")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Re-import the new commit of v1.4.0" }),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/reimport"))).toBe(false);
  });

  it("re-imports a moved tag on confirmation and follows its job", async () => {
    const calls = serve({ sync: () => synced([v(moved), v({ status: "up_to_date" })], 200) });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Re-sync now" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "Re-import the new commit of v1.4.0" }),
    );
    expect(await screen.findByText("job j11 for v1.4.0")).toBeInTheDocument();
    const sent = calls.find((c) => c.url.endsWith("/versions/reimport"));
    expect(sent).toMatchObject({
      method: "POST",
      url: "/api/v1/libraries/acme/payments/versions/reimport",
      body: { ref: "v1.4.0" },
    });
    // The error is over: the row is an update now, with the commits it moves between.
    expect(screen.queryByText(/tag now points at another commit/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Re-import/ })).not.toBeInTheDocument();
    expect(screen.getByText("1 version is updating.")).toBeInTheDocument();
    const commits = (_: string, el: Element | null) =>
      el?.tagName === "P" &&
      el.textContent === `${SHA.slice(0, 7)}${SHA2.slice(0, 7)} (previous commit to new commit)`;
    expect(screen.getByText(commits)).toBeInTheDocument();
  });

  it("explains a confirmation the server refuses, and keeps the row", async () => {
    serve({
      sync: () => synced([v(moved)], 200),
      reimport: () => failure(409, "tag_not_moved"),
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Re-sync now" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "Re-import the new commit of v1.4.0" }),
    );
    const said = await screen.findByText(/nothing to re-import/);
    expect(said.closest("p")).toHaveClass("bg-route-soft"); // not a mistake: neutral
    expect(screen.getByText(/tag now points at another commit/)).toBeInTheDocument();
    // Asking again would get the same answer.
    expect(screen.queryByRole("button", { name: /Re-import/ })).not.toBeInTheDocument();
  });

  it("explains 409 and 422", async () => {
    serve({ sync: () => failure(409, "version_importing") });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Re-sync now" }));
    const wait = await screen.findByText(/still importing/);
    // A wait state is neutral, not red.
    expect(wait.closest("p")).toHaveClass("bg-route-soft");

    serve({ sync: () => failure(422, "repo_unreachable", "failed job j7: unreachable") });
    await userEvent.click(screen.getByRole("button", { name: "Re-sync now" }));
    expect(await screen.findByText(/couldn't be read/)).toBeInTheDocument();
    // Job IDs mean nothing to a person: they are not shown.
    expect(screen.queryByText(/j7/)).not.toBeInTheDocument();
  });
});

describe("removing a version", () => {
  async function ask(ref = "main") {
    const trigger = await screen.findByRole("button", { name: `More actions for ${ref}` });
    await userEvent.click(trigger);
    await userEvent.click(await screen.findByRole("menuitem", { name: "Remove version…" }));
    return { trigger, dialog: await screen.findByRole("alertdialog") };
  }

  it("needs the version typed in full, then removes it", async () => {
    const calls = serve();
    renderPage();
    const { dialog } = await ask();
    const confirm = within(dialog).getByRole("button", { name: "Remove version" });
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    const input = within(dialog).getByLabelText(/Type main to confirm/);
    expect(input).toHaveFocus();
    await userEvent.click(confirm);
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.type(input, "mai");
    await userEvent.click(confirm);
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.type(input, "n");
    expect(confirm).not.toHaveAttribute("aria-disabled");
    await userEvent.click(confirm);
    expect(
      await screen.findByText(/Removed main\. The default version is now main\./),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.method === "DELETE")?.url).toMatch(/\/versions\/main$/);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Versions" })).toHaveFocus();
  });

  it("returns focus to the row's menu button it came from on cancel", async () => {
    serve();
    renderPage();
    const { trigger, dialog } = await ask();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("keeps the dialog and says why while an import runs", async () => {
    serve({ removeVersion: () => failure(409, "import_in_progress") });
    renderPage();
    const { dialog } = await ask();
    await userEvent.type(within(dialog).getByLabelText(/Type main/), "main");
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove version" }));
    expect(await within(dialog).findByText(/never cancels a job/)).toBeInTheDocument();
  });

  it("treats a version that is already gone as removed", async () => {
    serve({ removeVersion: () => failure(404, "not_found") });
    renderPage();
    const { dialog } = await ask();
    await userEvent.type(within(dialog).getByLabelText(/Type main/), "main");
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove version" }));
    expect(await screen.findByText("main was already removed.")).toBeInTheDocument();
  });
});

describe("removing the library", () => {
  it("needs the ID typed, removes, and leaves for the list", async () => {
    const calls = serve();
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Remove library…" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText(/Content that other libraries share stays available/),
    ).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/to confirm/), "/acme/payments");
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove library" }));
    expect(await screen.findByText("Libraries home")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "DELETE")?.url).toMatch(
      /\/v1\/libraries\/acme\/payments$/,
    );
  });

  it("explains 409 and stays", async () => {
    serve({ removeLibrary: () => failure(409, "import_in_progress") });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Remove library…" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.type(within(dialog).getByLabelText(/to confirm/), "/acme/payments");
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove library" }));
    expect(await within(dialog).findByText(/never cancels a job/)).toBeInTheDocument();
    expect(screen.queryByText("Libraries home")).not.toBeInTheDocument();
  });
});

describe("the page", () => {
  it("names the library in its heading", async () => {
    serve();
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "Payments" })).toBeInTheDocument();
    expect(screen.getByText("Library settings")).toBeInTheDocument();
  });

  it("leads back through the shared breadcrumb", async () => {
    serve();
    renderPage();
    const crumbs = within(await screen.findByRole("navigation", { name: "Breadcrumb" }));
    expect(crumbs.getByRole("link", { name: "Libraries" })).toHaveAttribute("href", "/");
    expect(crumbs.getByRole("link", { name: "/acme/payments" })).toHaveAttribute(
      "href",
      "/libraries/acme/payments",
    );
    expect(crumbs.getByText("Settings")).toHaveAttribute("aria-current", "page");
  });

  it("shows its layout with bars while the library loads", async () => {
    render(
      <TestRouter
        pages={{ "/libraries/$owner/$repo/settings": LibrarySettingsSkeleton }}
        start="/libraries/acme/payments/settings"
      />,
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Loading the library settings");
    expect(screen.getByRole("main")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("link", { name: "/acme/payments" })).toBeInTheDocument();
    expect(screen.getByText("Remove library", { selector: "h2" })).toBeInTheDocument();
  });

  it("falls back to the ID when the library has no title", async () => {
    serve();
    renderPage({ ...library, title: "" });
    expect(
      await screen.findByRole("heading", { level: 1, name: "/acme/payments" }),
    ).toBeInTheDocument();
  });

  it("explains that edits are kept only once something is edited", async () => {
    serve();
    renderPage();
    const title = await screen.findByLabelText("Title");
    const note = screen.getByText(/Edited fields are kept when the library is re-imported/);
    expect(note.closest("[inert]")).not.toBeNull();
    await userEvent.type(title, "!");
    expect(note.closest("[inert]")).toBeNull();
  });

  it("clears an old re-sync result when another action starts", async () => {
    serve({
      sync: () => ({
        status: 200,
        body: {
          library_id: "/acme/payments",
          versions: [
            {
              ref: "main",
              ref_kind: "branch",
              status: "up_to_date",
              previous_commit_sha: SHA,
              commit_sha: SHA,
              job_id: null,
            },
          ],
        },
      }),
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Re-sync now" }));
    expect(await screen.findByText(/Everything is up to date/)).toBeInTheDocument();
    expect(screen.getByText(/Checked/)).toBeInTheDocument();
    await removeFromMenu("main");
    await waitFor(() =>
      expect(screen.queryByText(/Everything is up to date/)).not.toBeInTheDocument(),
    );
  });
});

describe("removal while a request is in flight", () => {
  it("ignores Escape and Cancel until the server has answered", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    serve({ gate });
    renderPage();
    await removeFromMenu("main");
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.type(within(dialog).getByLabelText(/Type main/), "main");
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove version" }));
    await within(dialog).findByRole("button", { name: "Removing" });
    await userEvent.keyboard("{Escape}");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    release();
    expect(await screen.findByText(/Removed main/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("forgets the removed library only after leaving its page, then reloads the list", async () => {
    serve();
    const queryClient = renderPage();
    const libraryKey = [...BROWSE_KEY, "acme", "payments", "library"];
    queryClient.setQueryData(libraryKey, library);
    queryClient.setQueryData([...LIBRARIES_KEY, "list"], { libraries: [] });
    await userEvent.click(await screen.findByRole("button", { name: "Remove library…" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.type(within(dialog).getByLabelText(/to confirm/), "/acme/payments");
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove library" }));
    expect(await screen.findByText("Libraries home")).toBeInTheDocument();
    await waitFor(() => expect(queryClient.getQueryData(libraryKey)).toBeUndefined());
    expect(queryClient.getQueryState([...LIBRARIES_KEY, "list"])?.isInvalidated).toBe(true);
  });

  it("arms the confirm button only when the phrase matches", async () => {
    serve();
    renderPage();
    await removeFromMenu("main");
    const dialog = await screen.findByRole("alertdialog");
    const confirm = within(dialog).getByRole("button", { name: "Remove version" });
    expect(confirm).toHaveClass("aria-disabled:cursor-not-allowed");
    expect(confirm).not.toHaveClass("aria-disabled:cursor-progress");
    expect(within(dialog).getByLabelText(/Type main/)).toHaveClass("text-section");
  });
});

describe("adding a version of a private library", () => {
  const TOKEN = ["typed", "replacement", "value"].join("-");
  const cached = (queryClient: QueryClient) =>
    JSON.stringify([
      queryClient
        .getQueryCache()
        .getAll()
        .map((q) => [q.queryKey, q.state.data]),
      queryClient
        .getMutationCache()
        .getAll()
        .map((m) => [m.state.variables, m.state.data]),
    ]);

  it("asks for the token again when the stored one can't be read, and sends it once", async () => {
    let first = true;
    const calls = serve({
      addVersion: (body) => {
        if (first) {
          first = false;
          return failure(422, "credentials_required");
        }
        return {
          status: 202,
          body: {
            library_id: "/acme/payments",
            ref: body.ref,
            ref_kind: "tag",
            commit_sha: SHA,
            job_id: "j9",
          },
        };
      },
    });
    const queryClient = renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add a version" }));
    await userEvent.selectOptions(await screen.findByLabelText("Version to import"), "tag:v1.3.0");
    await userEvent.click(screen.getByRole("button", { name: "Add version" }));

    const box = await screen.findByLabelText("Access token");
    expect(box).toHaveAttribute("type", "password");
    expect(await screen.findByText(/can't be read any more/)).toBeInTheDocument();
    await waitFor(() => expect(box).toHaveFocus());
    await userEvent.type(box, TOKEN);
    expect(box.getAttribute("value")).toBeNull();
    expect(document.documentElement.outerHTML).not.toContain(TOKEN);
    await userEvent.click(screen.getByRole("button", { name: "Add version" }));

    expect(await screen.findByText("Importing v1.3.0")).toBeInTheDocument();
    const posts = calls.filter((c) => c.url.endsWith("/versions") && c.method === "POST");
    expect(posts.map((c) => c.body)).toEqual([
      { ref: "v1.3.0" },
      { ref: "v1.3.0", credential: { kind: "token", token: TOKEN } },
    ]);
    expect(calls.some((c) => c.url.includes(TOKEN))).toBe(false);
    expect(cached(queryClient)).not.toContain(TOKEN);
    expect(document.body.innerHTML).not.toContain(TOKEN);
  });

  it("lists a private repository's refs only with a typed token, by POST", async () => {
    const calls = serve({ private: true });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add a version" }));
    const box = await screen.findByLabelText("Access token");
    expect(screen.getByText(/Leave it empty to use the token stored/)).toBeInTheDocument();
    expect(await screen.findByText(/enter it above to see them/)).toBeInTheDocument();
    // Nothing is asked without a credential; typing alone asks nothing; leaving the box does, once.
    expect(calls.filter((c) => c.url.includes("/repositories/refs"))).toEqual([]);
    await userEvent.type(box, TOKEN);
    const refs = () => calls.filter((c) => c.url.includes("/repositories/refs"));
    expect(refs().filter((c) => c.method === "POST")).toEqual([]);
    await userEvent.tab();
    const picker = await screen.findByRole("combobox", { name: "Version to import" });
    expect(within(picker).getByRole("option", { name: "v1.3.0" })).toBeInTheDocument();
    expect(refs().filter((c) => c.method === "POST")).toEqual([
      {
        method: "POST",
        url: "/api/v1/repositories/refs",
        body: { url: library.source_url, credential: { kind: "token", token: TOKEN } },
      },
    ]);
    expect(calls.some((c) => c.url.includes(TOKEN))).toBe(false);
  });

  it("says at once that a replacement token can't read the repository", async () => {
    serve({ private: true, refs: () => failure(422, "repository_auth_required") });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add a version" }));
    await userEvent.type(await screen.findByLabelText("Access token"), TOKEN);
    await userEvent.tab();
    expect(await screen.findByText(/refused this token/)).toBeInTheDocument();
    expect(screen.queryByText(/Couldn't load branches and tags/)).not.toBeInTheDocument();
  });

  it("explains a refused replacement and a changed host key", () => {
    const e = (code: string) =>
      new HttpError(422, "/v1/x", { error: code, detail: "d", fields: [] });
    expect(explainAddVersion(e("repository_auth_required"), "v1", "token")).toMatchObject({
      field: "credential",
      message: expect.stringMatching(/refused this token/),
    });
    expect(explainAddVersion(e("repository_auth_required"), "v1").field).toBe("credential");
    expect(explainAddVersion(e("host_key_changed"), "v1").message).toMatch(/different host key/);
  });
});

describe("the versions table", () => {
  const version = (n: number) => ({
    ref: `v1.${n}.0`,
    kind: n % 5 === 0 ? "branch" : "tag",
    commit_sha: SHA,
    imported_at: "2026-11-01T10:00:00Z",
    is_default: n === 1,
    origin: n % 2 ? "manual" : "auto",
  });

  /**
   * A versions API over `count` versions that honours `limit`, an offset cursor (`o<n>`) and the
   * repeatable `kind` filter; everything else as `serve` answers it.
   */
  function serveVersions(count: number) {
    const calls = serve();
    const all = Array.from({ length: count }, (_, i) => version(i + 1));
    const real = globalThis.fetch;
    vi.stubGlobal("fetch", (input: string, init?: RequestInit) => {
      if (!String(input).includes("/versions?")) return real(input, init);
      calls.push({ method: "GET", url: String(input), body: undefined });
      const url = new URL(String(input), "http://x");
      const kinds = url.searchParams.getAll("kind");
      const rows = kinds.length ? all.filter((v) => kinds.includes(v.kind)) : all;
      const start = Number(url.searchParams.get("cursor")?.slice(1) ?? 0);
      const limit = Number(url.searchParams.get("limit"));
      return Promise.resolve(
        Response.json({
          library: library.id,
          versions: rows.slice(start, start + limit),
          next_cursor: start + limit < rows.length ? `o${start + limit}` : null,
          total: rows.length,
        }),
      );
    });
    return calls;
  }

  const listed = (calls: ReturnType<typeof serve>) =>
    calls.map((c) => c.url).filter((u) => u.includes("/versions?"));

  it("pages the versions, and filters and sorts them on the server", async () => {
    const calls = serveVersions(45);
    renderPage();
    const table = await screen.findByRole("table", { name: "Imported versions" });
    expect(await screen.findByText("1–20 of 45")).toBeInTheDocument();
    expect(within(table).getByText("v1.1.0")).toBeInTheDocument();
    expect(within(table).getByText("default")).toBeInTheDocument();
    expect(listed(calls)[0]).toBe("/api/v1/libraries/acme/payments/versions?limit=20");

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("21–40 of 45")).toBeInTheDocument();
    expect(within(table).getByText("v1.21.0")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Kind" }));
    await userEvent.click(await screen.findByRole("option", { name: "branch" }));
    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(listed(calls)).toContain(
        "/api/v1/libraries/acme/payments/versions?limit=20&kind=branch",
      ),
    );
    // A new filter starts again at page 1.
    expect(await screen.findByText("1–9 of 9")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Sort by Imported" }));
    await waitFor(() =>
      expect(listed(calls)).toContain(
        "/api/v1/libraries/acme/payments/versions?limit=20&kind=branch&sort=-imported_at",
      ),
    );
  });

  it("reads its view from the settings URL and shows the active filters", async () => {
    const calls = serveVersions(3);
    renderPage(
      library,
      "/libraries/acme/payments/settings?kind=tag,branch&origin=auto&sort=-origin",
    );
    await screen.findByRole("table", { name: "Imported versions" });
    expect(listed(calls)[0]).toBe(
      "/api/v1/libraries/acme/payments/versions?limit=20&kind=tag&kind=branch&origin=auto&sort=-origin",
    );
    const chips = screen.getByRole("list", { name: "Active filters" });
    expect(
      within(chips).getByRole("button", { name: "Remove filter Origin: auto" }),
    ).toBeInTheDocument();
  });

  it("offers the same actions in the row's menu and its context menu", async () => {
    serveVersions(3);
    renderPage();
    const table = await screen.findByRole("table", { name: "Imported versions" });
    await userEvent.click(
      await within(table).findByRole("button", { name: "More actions for v1.2.0" }),
    );
    const names = (menu: HTMLElement) =>
      within(menu)
        .getAllByRole("menuitem")
        .map((item) => item.textContent);
    const visible = names(await screen.findByRole("menu"));
    expect(visible).toEqual(["Browse this version", "Copy commit SHA", "Remove version…"]);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());

    const row = within(table).getByText("v1.2.0").closest("tr");
    fireEvent.contextMenu(row as HTMLElement);
    expect(names(await screen.findByRole("menu"))).toEqual(visible);
    await userEvent.click(screen.getByRole("menuitem", { name: "Browse this version" }));
    expect(await screen.findByText("Browse")).toBeInTheDocument();
  });

  it("says what to do when the library has no versions yet", async () => {
    serveVersions(0);
    renderPage({ ...library, versions: [] });
    expect(
      await screen.findByText("No versions yet. Add one, or wait for the first import to finish."),
    ).toBeInTheDocument();
  });
});

describe("in Polish", () => {
  const synced = (versions: unknown[]) => ({
    status: 202,
    body: { library_id: "/acme/payments", versions },
  });
  const row = (over: Record<string, unknown>) => ({
    ref: "main",
    ref_kind: "branch",
    status: "queued",
    previous_commit_sha: SHA,
    commit_sha: SHA2,
    job_id: "j5",
    error_code: null,
    ...over,
  });

  afterEach(() => resetPreferences());

  it("names the page, its sections and the versions table in Polish", async () => {
    setPreferences({ language: "pl" });
    serve();
    renderPage();
    expect(await screen.findByRole("heading", { name: "Szczegóły" })).toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe("Ustawienia: Payments - ExactDocs"));
    expect(screen.getByRole("navigation", { name: "Na tej stronie" })).toBeInTheDocument();
    for (const name of ["Pliki i tagi", "Wersje", "Udostępnianie", "Usuń bibliotekę"]) {
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "Zarządzaj udostępnianiem" })).toBeInTheDocument();
    const crumbs = within(screen.getByRole("navigation", { name: "Ścieżka nawigacji" }));
    expect(crumbs.getByRole("link", { name: "Biblioteki" })).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Tytuł"), "!");
    expect(await screen.findByText("1 sekcja ma niezapisane zmiany.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz zmiany" })).toBeInTheDocument();

    const table = await screen.findByRole("table", { name: "Zaimportowane wersje" });
    expect(await within(table).findByText("gałąź")).toBeInTheDocument();
    expect(within(table).getByText("domyślna")).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Więcej opcji: main" })).toBeVisible();
    expect(screen.getByLabelText("Znajdź wersję")).toHaveAttribute("placeholder", "Ref lub commit");
    expect(screen.getByRole("button", { name: "Pochodzenie" })).toBeInTheDocument();
    await userEvent.click(within(table).getByRole("button", { name: "Więcej opcji: main" }));
    const menu = within(await screen.findByRole("menu"));
    expect(menu.getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "Przeglądaj tę wersję",
      "Kopiuj SHA commita",
      "Usuń wersję…",
    ]);
  });

  it("asks for the version typed, and says why it stays while an import runs", async () => {
    setPreferences({ language: "pl" });
    serve({ removeVersion: () => failure(409, "import_in_progress") });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Więcej opcji: main" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Usuń wersję…" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Usunąć main?" });
    await userEvent.type(within(dialog).getByLabelText("Wpisz main, aby potwierdzić"), "main");
    await userEvent.click(within(dialog).getByRole("button", { name: "Usuń wersję" }));
    expect(
      await within(dialog).findByText(/^Import wersji main wciąż trwa\. Usuwanie nigdy/),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Anuluj" })).toBeInTheDocument();
  });

  it("says what removing the library takes, with the right plural", async () => {
    setPreferences({ language: "pl" });
    serve();
    renderPage();
    const danger = within(await screen.findByRole("region", { name: "Usuń bibliotekę" }));
    expect(danger.getByText(/wraz z jej 2 wersjami\. Zniknie z przeglądania/)).toHaveTextContent(
      /^Usuń bibliotekę \/acme\/payments wraz z jej 2 wersjami\./,
    );
    await userEvent.click(danger.getByRole("button", { name: "Usuń bibliotekę…" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Wszystkie 2 wersje (v1.2.0, main) i ich artykuły");
  });

  it("reports a re-sync in Polish", async () => {
    setPreferences({ language: "pl" });
    serve({
      sync: () =>
        synced([
          row({}),
          row({ ref: "next", status: "failed", job_id: null, error_code: "ref_deleted" }),
          row({ ref: "v1.2.0", ref_kind: "tag", status: "pinned", job_id: null }),
        ]),
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Synchronizuj teraz" }));
    expect(
      await screen.findByText("1 wersja jest aktualizowana, nie udało się sprawdzić 1 wersji."),
    ).toBeInTheDocument();
    expect(screen.getByText("Sprawdzono", { exact: false })).toHaveTextContent(
      "Sprawdzono przed chwilą.",
    );
    expect(screen.getByText("Błąd")).toBeInTheDocument();
    expect(screen.getByText(/^Gałęzi nie ma już w repozytorium\./)).toBeInTheDocument();
    expect(screen.getByText("v1.2.0 jest przypięta i nigdy się nie zmienia.")).toBeInTheDocument();
  });

  it("words plurals and refusals in Polish", () => {
    const versions = (n: number, status: string) =>
      Array.from({ length: n }, (_, i) => row({ ref: `v${i}`, status }));
    const headline = (...v: unknown[][]) =>
      syncHeadline({ library_id: "x", versions: v.flat() } as never, "pl");
    expect(headline(versions(2, "queued"))).toBe("2 wersje są aktualizowane.");
    expect(headline(versions(5, "queued"))).toBe("5 wersji jest aktualizowanych.");
    expect(headline(versions(22, "queued"))).toBe("22 wersje są aktualizowane.");
    expect(headline(versions(3, "failed"))).toBe("Nie udało się sprawdzić 3 wersji.");
    expect(headline(versions(1, "up_to_date"))).toBe("Wszystko jest aktualne.");
    expect(statusWords("up_to_date", "pl")).toBe("Aktualna");
    expect(validateDetails({ title: "x".repeat(201), description: "" }, "pl").title).toBe(
      "Tytuł może mieć najwyżej 200 znaków.",
    );
    expect(explainSync(new TypeError("offline"), "pl").message).toMatch(/^Nie można połączyć/);
    expect(
      explainRemove(
        new HttpError(401, "/v1/x", { error: "unauthenticated", detail: "d", fields: [] }),
        "z",
        "pl",
      ),
    ).toMatchObject({
      message: "Twoja sesja wygasła.",
      link: { href: "/sign-in", label: "Zaloguj się" },
    });
    expect(
      explainAddVersion(
        new HttpError(409, "/v1/x", { error: "version_exists", detail: "d", fields: [] }),
        "v1",
        undefined,
        "pl",
      ),
    ).toMatchObject({
      message: "„v1” jest już wersją tej biblioteki.",
    });
  });
});
