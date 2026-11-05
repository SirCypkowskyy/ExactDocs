import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { RENAME_LOOKUP_TIMEOUT_MS } from "../api/browse-queries";
import type { RenamedPath, Version } from "../model/browse";
import { VersionPicker } from "./version-picker";

const version = (ref: string, sha: string): Version => ({
  ref,
  kind: "tag",
  commit_sha: sha.repeat(40),
  imported_at: "2026-11-01T10:00:00Z",
  is_default: ref === "v1.4.0",
});
const versions = [version("v1.4.0", "b"), version("v1.3.0", "a"), version("v1.2.0", "9")];
const rename: RenamedPath = {
  library: "/fixture/docs-repo",
  ref: "v1.4.0",
  from_ref: "v1.3.0",
  old_path: "guide/setup.md",
  new_path: "guide/install.md",
  similarity: 90,
};

type Answer = { status: number; body: unknown };

/**
 * The rename map of v1.4.0: `guide/setup.md` of v1.3.0 is `guide/install.md` there. `hold` keeps
 * the answers for one ref back until the returned release is called; `status` fails them all.
 */
function serve(status = 200, hold: Record<string, Promise<void>> = {}) {
  const answer = (url: string): Answer => {
    const { searchParams: q } = new URL(url, "http://test");
    const forward = q.get("direction") === "forward" && q.get("path") === "guide/setup.md";
    const back = q.get("direction") === "back" && q.get("path") === "guide/install.md";
    const hit = q.get("ref") === "v1.4.0" && (forward || back);
    return { status, body: status === 200 ? { renamed: hit ? rename : null } : {} };
  };
  const fetch = vi.fn(async (url: string) => {
    const ref = new URL(url, "http://test").searchParams.get("ref") ?? "";
    await hold[ref];
    const { status: code, body } = answer(url);
    return new Response(JSON.stringify(body), {
      status: code,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

/** A promise held open until `release` is called. */
function gate() {
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { held, release };
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
  // Like the app's client: failed queries are retried, so a lookup that is retried shows up as a wait.
  const client = new QueryClient({ defaultOptions: { queries: { retry: 2 } } });
  return render(
    <QueryClientProvider client={client}>
      <TestRouter pages={{ "/": Page, "/libraries/$owner/$repo": Page }} start={start} />
    </QueryClientProvider>,
  );
}

const linkTo = (ref: string) =>
  screen.getByRole("link", { name: new RegExp(ref.replaceAll(".", "\\.")) });

async function openPicker() {
  await userEvent.click(await screen.findByRole("button", { name: /Change version/ }));
}

async function switchTo(ref: string) {
  await openPicker();
  await userEvent.click(linkTo(ref));
}

const showing = () => screen.findByRole("status", { name: "Showing" });

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

  it("keeps the path without waiting when the rename map answers with a server error", async () => {
    serve(503);
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await switchTo("v1.4.0");
    // Retried with backoff, the switch would take seconds; findBy gives up after one.
    expect(await showing()).toHaveTextContent("v1.4.0 guide/setup.md");
  });

  it("gives up on a rename lookup that does not answer in time", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
          }),
      ),
    );
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await switchTo("v1.4.0");
    expect(await showing()).toHaveTextContent("v1.3.0 guide/setup.md");
    expect(
      await screen.findByText(
        "v1.4.0 guide/setup.md",
        {},
        { timeout: RENAME_LOOKUP_TIMEOUT_MS * 2 },
      ),
    ).toBeInTheDocument();
  });

  it("puts the renamed path into the link once the list is open, for a new tab or a copied link", async () => {
    serve();
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await openPicker();
    await waitFor(() =>
      expect(linkTo("v1.4.0")).toHaveAttribute(
        "href",
        expect.stringContaining("path=guide%2Finstall.md"),
      ),
    );
    expect(linkTo("v1.2.0")).toHaveAttribute(
      "href",
      expect.stringContaining("path=guide%2Fsetup.md"),
    );
  });

  it("leaves a modifier click to the browser", async () => {
    serve();
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await openPicker();
    const link = linkTo("v1.4.0");
    await waitFor(() => expect(link).toHaveAttribute("href", expect.stringContaining("install")));
    // Read after React's handlers ran (they listen on the root, below the document).
    let prevented: boolean | undefined;
    const record = (event: Event) => {
      prevented = event.defaultPrevented;
      event.preventDefault(); // jsdom cannot open a tab; keep the test page where it is
    };
    document.addEventListener("click", record);
    const user = userEvent.setup();
    await user.keyboard("{Control>}");
    await user.click(link);
    await user.keyboard("{/Control}");
    document.removeEventListener("click", record);
    expect(prevented).toBe(false);
    expect(await showing()).toHaveTextContent("v1.3.0 guide/setup.md");
  });

  it("follows the rename from the keyboard", async () => {
    serve();
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await openPicker();
    linkTo("v1.4.0").focus();
    await userEvent.keyboard("{Enter}");
    expect(await showing()).toHaveTextContent("v1.4.0 guide/install.md");
  });

  it("keeps the later of two quick switches when the first answer arrives last", async () => {
    const slow = gate();
    const fast = gate();
    serve(200, { "v1.4.0": slow.held, "v1.2.0": fast.held });
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await switchTo("v1.4.0");
    const trigger = screen.getByRole("button", { name: /Change version/ });
    expect(trigger).toHaveAttribute("aria-busy", "true");
    expect(trigger).toHaveAccessibleName(/switching to v1\.4\.0/);
    await switchTo("v1.2.0");
    fast.release();
    expect(await screen.findByText("v1.2.0 guide/setup.md")).toBeInTheDocument();
    slow.release();
    await waitFor(() => expect(trigger).not.toHaveAttribute("aria-busy"));
    // Give a late navigation the chance to happen before checking it did not.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(await showing()).toHaveTextContent("v1.2.0 guide/setup.md");
  });

  it("does not switch late when the user went elsewhere while waiting", async () => {
    const slow = gate();
    serve(200, { "v1.4.0": slow.held });
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await openPicker();
    // v1.2.0 has its answer: a plain link, followed at once while v1.4.0 still waits.
    await waitFor(() =>
      expect(linkTo("v1.2.0")).toHaveAttribute("href", expect.stringContaining("v1.2.0")),
    );
    await userEvent.click(linkTo("v1.4.0"));
    await switchTo("v1.2.0");
    expect(await screen.findByText("v1.2.0 guide/setup.md")).toBeInTheDocument();
    slow.release();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(await showing()).toHaveTextContent("v1.2.0 guide/setup.md");
  });
});
