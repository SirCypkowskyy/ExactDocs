import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import type { RenamedPath, Version } from "../model/browse";
import { VersionPicker } from "./version-picker";

const version = (ref: string, sha: string): Version => ({
  ref,
  kind: "tag",
  commit_sha: sha.repeat(40),
  imported_at: "2026-11-01T10:00:00Z",
  is_default: ref === "v1.4.0",
});
const versions = [version("v1.4.0", "b"), version("v1.3.0", "a")];
const rename: RenamedPath = {
  library: "/fixture/docs-repo",
  ref: "v1.4.0",
  from_ref: "v1.3.0",
  old_path: "guide/setup.md",
  new_path: "guide/install.md",
  similarity: 90,
};

/** The rename map of v1.4.0: `guide/setup.md` of v1.3.0 is `guide/install.md` there. */
function serve(status = 200) {
  const fetch = vi.fn((url: string) => {
    const { searchParams: q } = new URL(url, "http://test");
    const forward = q.get("direction") === "forward" && q.get("path") === "guide/setup.md";
    const back = q.get("direction") === "back" && q.get("path") === "guide/install.md";
    const hit = q.get("ref") === "v1.4.0" && (forward || back);
    return Promise.resolve(
      new Response(JSON.stringify(status === 200 ? { renamed: hit ? rename : null } : {}), {
        status,
        headers: { "content-type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

/** The browse page reduced to the picker, with the URL's version and path printed under it. */
function Page() {
  const search = useRouterState({ select: (s) => s.location.search }) as Record<string, string>;
  const ref = search.version ?? "v1.3.0";
  const path = search.path;
  return (
    <>
      <VersionPicker
        owner="fixture"
        repo="docs-repo"
        versions={versions}
        current={versions.find((v) => v.ref === ref) ?? version("v1.3.0", "a")}
        keep={{ path }}
      />
      <output aria-label="Showing">
        {ref} {path ?? "(root)"}
      </output>
    </>
  );
}

function view(start: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TestRouter pages={{ "/": Page, "/libraries/$owner/$repo": Page }} start={start} />
    </QueryClientProvider>,
  );
}

async function switchTo(ref: string) {
  await userEvent.click(await screen.findByRole("button", { name: /Change version/ }));
  await userEvent.click(screen.getByRole("link", { name: new RegExp(ref.replaceAll(".", "\\.")) }));
}

afterEach(() => vi.unstubAllGlobals());

describe("VersionPicker", () => {
  it("opens the renamed article when switching to the version that renamed it", async () => {
    serve();
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await switchTo("v1.4.0");
    expect(await screen.findByRole("status", { name: "Showing" })).toHaveTextContent(
      "v1.4.0 guide/install.md",
    );
  });

  it("follows the rename back to the older version", async () => {
    serve();
    view("/libraries/fixture/docs-repo?version=v1.4.0&path=guide%2Finstall.md");
    await switchTo("v1.3.0");
    expect(await screen.findByRole("status", { name: "Showing" })).toHaveTextContent(
      "v1.3.0 guide/setup.md",
    );
  });

  it("keeps a path that was not renamed", async () => {
    serve();
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fauth.md");
    await switchTo("v1.4.0");
    expect(await screen.findByRole("status", { name: "Showing" })).toHaveTextContent(
      "v1.4.0 guide/auth.md",
    );
  });

  it("keeps the path when the rename map cannot be read", async () => {
    serve(404);
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await switchTo("v1.4.0");
    expect(await screen.findByRole("status", { name: "Showing" })).toHaveTextContent(
      "v1.4.0 guide/setup.md",
    );
  });

  it("asks nothing when no article is open", async () => {
    const fetch = serve();
    view("/libraries/fixture/docs-repo?version=v1.3.0");
    await switchTo("v1.4.0");
    expect(await screen.findByRole("status", { name: "Showing" })).toHaveTextContent(
      "v1.4.0 (root)",
    );
    expect(fetch).not.toHaveBeenCalled();
  });
});
