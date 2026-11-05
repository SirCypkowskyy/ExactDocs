import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { TestRouter } from "@/shared/lib/test-router";
import { AddLibraryPage } from "./index";
import {
  buildFileTree,
  explainAddError,
  explainPreviewError,
  previewCountText,
  previewKey,
} from "./model/add-library";

const SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678";
const URL_ = "https://github.com/acme/payments";

type Reply = { status: number; body: unknown; headers?: Record<string, string> };

const PREVIEW = {
  ref: "main",
  ref_kind: "branch",
  commit_sha: SHA,
  files: ["README.md", "docs/guides/intro.md", "docs/guides/setup.md", "docs/index.md"],
  total: 4,
  truncated: false,
  include_paths: [],
  exclude_paths: [],
  context7: null,
  context7_warning: null,
};

const CONTEXT7 = {
  project_title: "Payments",
  description: "Card payments SDK",
  folders: ["docs"],
  exclude_folders: ["internal"],
  exclude_files: [],
  include_paths: ["docs/**"],
  exclude_paths: ["**/internal/**"],
  rules: ["Use the v2 client", "Never log card numbers"],
  previous_versions: [
    { tag: "v1.3.0", title: "1.3" },
    { tag: "v1.2.0", title: "" },
  ],
  notes: ["previousVersions entry “a..b” is not a valid tag name and was left out."],
};

const job = (id: string) => ({
  id,
  kind: "import",
  library: "/acme/payments",
  version: "main",
  commit_sha: SHA,
  state: "running",
  done: 0,
  total: 0,
  problems: [],
  error: null,
  created_at: "2026-11-01T10:00:00Z",
  started_at: null,
  finished_at: null,
});

function serve(
  routes: {
    preview?: (body: Record<string, unknown>) => Reply;
    version?: (ref: string) => Reply;
  } = {},
) {
  const preview = vi.fn(
    (body: Record<string, unknown>): Reply =>
      routes.preview?.(body) ?? { status: 200, body: PREVIEW },
  );
  const create = vi.fn((_body: Record<string, unknown>) => ({
    status: 201,
    body: {
      library_id: "/acme/payments",
      ref: "main",
      ref_kind: "branch",
      commit_sha: SHA,
      job_id: "j1",
    },
  }));
  const version = vi.fn(
    (ref: string): Reply =>
      routes.version?.(ref) ?? {
        status: 201,
        body: {
          library_id: "/acme/payments",
          ref,
          ref_kind: "tag",
          commit_sha: SHA,
          job_id: `job-${ref}`,
        },
      },
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const reply = (r: Reply) =>
        Response.json(r.body, { status: r.status, ...(r.headers && { headers: r.headers }) });
      const body = () => JSON.parse(String(init?.body)) as Record<string, unknown>;
      if (url.endsWith("/v1/repositories/check")) {
        return reply({
          status: 200,
          body: { host: "github", library_id: "/acme/payments", default_branch: "main" },
        });
      }
      if (url.includes("/v1/repositories/refs")) {
        return reply({
          status: 200,
          body: {
            default_branch: "main",
            branches: [{ name: "main", commit_sha: SHA }],
            tags: [{ name: "v1.4.0", commit_sha: SHA }],
            truncated: false,
          },
        });
      }
      if (url.endsWith("/v1/repositories/preview")) return reply(preview(body()));
      if (url.endsWith("/v1/libraries/acme/payments/versions")) {
        return reply(version(String(body().ref)));
      }
      if (url.endsWith("/v1/libraries") && init?.method === "POST") return reply(create(body()));
      const jobId = url.match(/\/v1\/jobs\/([^/?]+)/)?.[1];
      if (jobId) return Response.json(job(decodeURIComponent(jobId)));
      return new Response("{}", { status: 404 });
    }),
  );
  return { preview, create, version };
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
}

async function checkRepo() {
  await userEvent.type(await screen.findByLabelText("Repository address"), URL_);
  await userEvent.click(screen.getByRole("button", { name: "Check repository" }));
  await screen.findByLabelText("Version to import");
}

const previewButton = () => screen.getByRole("button", { name: "Preview" });

describe("preview model", () => {
  it("builds a folder tree with counts, merging folders that only hold one folder", () => {
    const tree = buildFileTree(["README.md", "docs/a/b/x.md", "docs/a/b/y.md", "docs/z.md"]);
    expect(tree.count).toBe(4);
    expect(tree.files).toEqual(["README.md"]);
    const docs = tree.folders[0];
    expect(docs?.name).toBe("docs");
    expect(docs?.count).toBe(3);
    expect(docs?.files).toEqual(["z.md"]);
    expect(docs?.folders.map((f) => [f.name, f.count, f.files])).toEqual([
      ["a/b", 2, ["x.md", "y.md"]],
    ]);
  });

  it("counts honestly, also when the list is cut", () => {
    expect(previewCountText({ total: 0, truncated: false, files: [] })).toBe(
      "No Markdown files match.",
    );
    expect(previewCountText({ total: 1, truncated: false, files: ["a.md"] })).toBe(
      "1 file matches.",
    );
    const many = Array.from({ length: 1000 }, (_, i) => `${i}.md`);
    expect(previewCountText({ total: 4213, truncated: true, files: many })).toBe(
      "4,213 files match. The first 1,000 are listed.",
    );
  });

  it("keys a preview by what it was asked, ignoring blank lines and spaces", () => {
    const a = previewKey({ url: URL_, ref: null, include: "docs/\n\n", exclude: "" });
    expect(previewKey({ url: URL_, ref: null, include: " docs/ ", exclude: "\n" })).toBe(a);
    expect(previewKey({ url: URL_, ref: "v1", include: "docs/", exclude: "" })).not.toBe(a);
  });

  it("explains a busy server with the wait it asked for", () => {
    const busy = (retry?: number) =>
      new HttpError(429, "/v1/x", { error: "preview_busy", detail: "d", fields: [] }, retry);
    expect(explainPreviewError(busy(7), null).message).toMatch(/busy.*Try again in 7 seconds/);
    expect(explainPreviewError(busy(), null).message).toMatch(/Try again in a moment/);
    expect(explainAddError(busy(1), null).message).toMatch(/context7\.json.*1 second\./);
    const bad = new HttpError(422, "/v1/x", {
      error: "invalid_path_pattern",
      detail: "d",
      fields: [],
    });
    expect(explainPreviewError(bad, null).field).toBe("paths");
  });
});

describe("add library preview", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("previews the matching tree with its file count before importing", async () => {
    const { preview, create } = serve();
    renderAdd();
    await checkRepo();
    await userEvent.selectOptions(screen.getByLabelText("Version to import"), "tag:v1.4.0");
    await userEvent.click(screen.getByText("Choose files and tags"));
    await userEvent.type(screen.getByLabelText("Only these paths"), "docs/\nREADME.md");
    await userEvent.click(previewButton());

    const section = await screen.findByRole("region", { name: "Files to import" });
    expect(preview).toHaveBeenCalledWith({
      url: URL_,
      ref: "v1.4.0",
      include_paths: ["docs/", "README.md"],
      exclude_paths: [],
    });
    expect(within(section).getByText("4 files match.")).toBeInTheDocument();
    const files = within(section).getByRole("region", { name: "Matching files" });
    // Folders first with the files below them, then the root's own files.
    expect(files).toHaveTextContent("docs/ (3)guides/ (2)intro.mdsetup.mdindex.mdREADME.md");
    // Announced once, as a count.
    await waitFor(() =>
      expect(screen.getAllByRole("status").some((s) => s.textContent === "4 files match.")).toBe(
        true,
      ),
    );
    // Nothing was added by a preview.
    expect(create).not.toHaveBeenCalled();
  });

  it("marks the preview out of date when the paths change", async () => {
    serve();
    renderAdd();
    await checkRepo();
    await userEvent.click(previewButton());
    await screen.findByRole("region", { name: "Files to import" });
    expect(screen.queryByText(/The form changed since this preview/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("Choose files and tags"));
    await userEvent.type(screen.getByLabelText("Leave out"), "docs/internal/**");
    expect(screen.getByText(/The form changed since this preview/)).toBeInTheDocument();
  });

  it("says when nothing matches", async () => {
    serve({ preview: () => ({ status: 200, body: { ...PREVIEW, files: [], total: 0 } }) });
    renderAdd();
    await checkRepo();
    await userEvent.click(previewButton());
    const section = await screen.findByRole("region", { name: "Files to import" });
    expect(within(section).getByText("No Markdown files match.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Matching files" })).not.toBeInTheDocument();
  });

  it("pre-fills the paths from context7.json and shows what it says", async () => {
    const { create } = serve({
      preview: () => ({
        status: 200,
        body: {
          ...PREVIEW,
          include_paths: CONTEXT7.include_paths,
          exclude_paths: CONTEXT7.exclude_paths,
          context7: CONTEXT7,
        },
      }),
    });
    renderAdd();
    await checkRepo();
    await userEvent.click(previewButton());
    const section = await screen.findByRole("region", { name: "Files to import" });
    expect(within(section).getByText("This repository has a context7.json.")).toBeInTheDocument();
    expect(within(section).getByText("Payments")).toBeInTheDocument();
    expect(within(section).getByText("Card payments SDK")).toBeInTheDocument();
    expect(within(section).getByText(/Its 2 rules are shown to agents/)).toBeInTheDocument();
    expect(within(section).getByText(/“a\.\.b” is not a valid tag name/)).toBeInTheDocument();
    // The paths it applied are in the boxes, editable, and the preview is not out of date.
    expect(screen.getByLabelText("Only these paths")).toHaveValue("docs/**");
    expect(screen.getByLabelText("Leave out")).toHaveValue("**/internal/**");
    expect(screen.queryByText(/The form changed since this preview/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    await screen.findByRole("heading", { name: /Importing/ });
    expect(create.mock.calls[0]?.[0]).toMatchObject({
      include_paths: ["docs/**"],
      exclude_paths: ["**/internal/**"],
    });
  });

  it("keeps paths the user typed over those of context7.json", async () => {
    serve({
      preview: (body) => ({
        status: 200,
        body: {
          ...PREVIEW,
          include_paths: body.include_paths,
          exclude_paths: [],
          context7: CONTEXT7,
        },
      }),
    });
    renderAdd();
    await checkRepo();
    await userEvent.click(screen.getByText("Choose files and tags"));
    await userEvent.type(screen.getByLabelText("Only these paths"), "guides/");
    await userEvent.click(previewButton());
    await screen.findByRole("region", { name: "Files to import" });
    expect(screen.getByLabelText("Only these paths")).toHaveValue("guides/");
    expect(screen.queryByText(/Its paths are filled in/)).not.toBeInTheDocument();
  });

  it("says why an invalid context7.json is ignored", async () => {
    serve({
      preview: () => ({
        status: 200,
        body: { ...PREVIEW, context7_warning: "context7.json is not valid JSON." },
      }),
    });
    renderAdd();
    await checkRepo();
    await userEvent.click(previewButton());
    expect(
      await screen.findByText("This repository's context7.json is ignored."),
    ).toBeInTheDocument();
    expect(screen.getByText("context7.json is not valid JSON.")).toBeInTheDocument();
  });

  it("imports the older versions ticked from previousVersions after the library", async () => {
    const { version } = serve({
      preview: () => ({ status: 200, body: { ...PREVIEW, context7: CONTEXT7 } }),
      version: (ref) =>
        ref === "v1.2.0"
          ? {
              status: 404,
              body: { error: "unknown_ref", detail: "no such ref", fields: [] },
            }
          : {
              status: 201,
              body: {
                library_id: "/acme/payments",
                ref,
                ref_kind: "tag",
                commit_sha: SHA,
                job_id: `job-${ref}`,
              },
            },
    });
    renderAdd();
    await checkRepo();
    await userEvent.click(previewButton());
    const older = await screen.findByRole("group", { name: "Also import older versions" });
    const boxes = within(older).getAllByRole("checkbox");
    expect(boxes.map((b) => b.closest("label")?.textContent)).toEqual(["v1.3.01.3", "v1.2.0"]);
    await userEvent.click(within(older).getByRole("checkbox", { name: /v1\.3\.0/ }));
    await userEvent.click(within(older).getByRole("checkbox", { name: /v1\.2\.0/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));

    const extras = await screen.findByRole("region", { name: "Older versions" });
    await waitFor(() => expect(version).toHaveBeenCalledTimes(2));
    expect(version.mock.calls.map((c) => c[0])).toEqual(["v1.3.0", "v1.2.0"]);
    expect(
      await within(extras).findByText(
        /Not queued\. This repository has no branch, tag or commit “v1\.2\.0”/,
      ),
    ).toBeInTheDocument();
    expect(await within(extras).findByText("Reading the repository")).toBeInTheDocument();
  });

  /** Preview with context7.json, tick the given tags, add the library; returns the version route. */
  async function addWithOlder(tags: string[], version?: (ref: string) => Reply) {
    const served = serve({
      preview: () => ({ status: 200, body: { ...PREVIEW, context7: CONTEXT7 } }),
      ...(version && { version }),
    });
    renderAdd();
    await checkRepo();
    await userEvent.click(previewButton());
    const older = await screen.findByRole("group", { name: "Also import older versions" });
    for (const tag of tags) {
      await userEvent.click(within(older).getByRole("checkbox", { name: new RegExp(tag) }));
    }
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    return { ...served, extras: await screen.findByRole("region", { name: "Older versions" }) };
  }

  const refusal = (code: string, detail: string) => () => ({
    status: 409,
    body: { error: code, detail, fields: [] },
  });

  it.each([
    [
      "version_importing",
      "an import of 'v1.3.0' into library '/acme/payments' is already in progress",
      "Not queued. Already being imported.",
    ],
    [
      "version_exists",
      "library '/acme/payments' already has a version 'v1.3.0'",
      "Not queued. Already a version of this library.",
    ],
    [
      "commit_already_imported",
      `commit ${SHA} is already the version 'main' of library '/acme/payments'`,
      "Not queued. Same commit as version main, already imported.",
    ],
  ])(
    "explains a %s refusal of an older version, with nothing to try again",
    async (code, detail, text) => {
      const { extras } = await addWithOlder(["v1.3.0"], refusal(code, detail));
      expect(await within(extras).findByText(text)).toBeInTheDocument();
      expect(within(extras).queryByRole("button", { name: /Try again/ })).not.toBeInTheDocument();
    },
  );

  it("lets a failed older version be tried again", async () => {
    let fail = true;
    const { version, extras } = await addWithOlder(["v1.3.0"], (ref) =>
      fail
        ? { status: 500, body: { error: "internal", detail: "boom", fields: [] } }
        : {
            status: 201,
            body: {
              library_id: "/acme/payments",
              ref,
              ref_kind: "tag",
              commit_sha: SHA,
              job_id: `job-${ref}`,
            },
          },
    );
    expect(
      await within(extras).findByText(/Something went wrong on the server \(500\)/),
    ).toBeInTheDocument();
    fail = false;
    await userEvent.click(
      within(extras).getByRole("button", { name: "Try again to import v1.3.0" }),
    );
    // The button unmounts with the retry; the keyboard stays on that tag's row, not the page top.
    const row = within(extras).getByText("v1.3.0");
    expect(document.activeElement).toBe(row);
    expect(await within(extras).findByText("Reading the repository")).toBeInTheDocument();
    expect(document.activeElement).toBe(row);
    expect(version).toHaveBeenCalledTimes(2);
  });

  it("does not offer, or queue, the tag picked as the version to import", async () => {
    const { version } = serve({
      preview: () => ({ status: 200, body: { ...PREVIEW, context7: CONTEXT7 } }),
    });
    renderAdd();
    await checkRepo();
    await userEvent.click(previewButton());
    const older = await screen.findByRole("group", { name: "Also import older versions" });
    await userEvent.click(within(older).getByRole("checkbox", { name: /v1\.3\.0/ }));
    await userEvent.click(within(older).getByRole("checkbox", { name: /v1\.2\.0/ }));
    // v1.3.0 becomes the version this add imports: it leaves the list of older ones.
    await userEvent.selectOptions(screen.getByLabelText("Version to import"), "other");
    await userEvent.type(screen.getByLabelText(/Branch, tag or commit/), "v1.3.0");
    expect(within(older).queryByRole("checkbox", { name: /v1\.3\.0/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    await screen.findByRole("region", { name: "Older versions" });
    await waitFor(() => expect(version).toHaveBeenCalledTimes(1));
    expect(version.mock.calls[0]?.[0]).toBe("v1.2.0");
  });

  it("queues no older version when none is ticked", async () => {
    const { version } = serve({
      preview: () => ({ status: 200, body: { ...PREVIEW, context7: CONTEXT7 } }),
    });
    renderAdd();
    await checkRepo();
    await userEvent.click(previewButton());
    await screen.findByRole("group", { name: "Also import older versions" });
    await userEvent.click(screen.getByRole("button", { name: "Add library" }));
    await screen.findByRole("heading", { name: /Importing/ });
    expect(screen.queryByRole("region", { name: "Older versions" })).not.toBeInTheDocument();
    expect(version).not.toHaveBeenCalled();
  });

  it("asks to wait when every preview slot is busy", async () => {
    serve({
      preview: () => ({
        status: 429,
        body: { error: "preview_busy", detail: "busy", fields: [] },
        headers: { "Retry-After": "5" },
      }),
    });
    renderAdd();
    await checkRepo();
    await userEvent.click(previewButton());
    expect(await screen.findByRole("alert")).toHaveTextContent(/Try again in 5 seconds/);
  });

  it("checks the paths locally before previewing", async () => {
    const { preview } = serve();
    renderAdd();
    await checkRepo();
    await userEvent.click(screen.getByText("Choose files and tags"));
    await userEvent.type(screen.getByLabelText("Only these paths"), "/etc/passwd");
    await userEvent.click(previewButton());
    expect(await screen.findByText(/starts with \//)).toBeInTheDocument();
    expect(preview).not.toHaveBeenCalled();
  });

  it("forgets the preview when the address changes", async () => {
    serve();
    renderAdd();
    await checkRepo();
    await userEvent.click(previewButton());
    await screen.findByRole("region", { name: "Files to import" });
    await userEvent.type(screen.getByLabelText("Repository address"), "-x");
    expect(screen.queryByRole("region", { name: "Files to import" })).not.toBeInTheDocument();
  });
});
