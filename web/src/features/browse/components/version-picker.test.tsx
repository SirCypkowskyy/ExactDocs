import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BROWSE_KEY, LIBRARIES_KEY } from "@/shared/lib/query-keys";
import { TestRouter } from "@/shared/lib/test-router";
import { pathInVersionQueryOptions, RENAME_LOOKUP_TIMEOUT_MS } from "../api/browse-queries";
import type { RenamedPath, Version } from "../model/browse";
import { VersionPicker } from "./version-picker";

const version = (ref: string, sha: string): Version => ({
  ref,
  kind: "tag",
  commit_sha: sha.repeat(40),
  imported_at: "2026-11-01T10:00:00Z",
  is_default: ref === "v1.4.0",
  origin: "manual",
});
const versions = [version("v1.4.0", "b"), version("v1.3.0", "a"), version("v1.2.0", "9")];
/** The import order; v1.4.0 renamed `guide/setup.md` of v1.3.0 to `guide/install.md`. */
const imported = ["v1.2.0", "v1.3.0", "v1.4.0"];
const RENAMED_IN = imported.indexOf("v1.4.0");

/** What the server answers for `path` of `from` in `to`, walking the versions in between. */
function renamedPath(from: string, to: string, path: string): RenamedPath | null {
  const [start, target] = [imported.indexOf(from), imported.indexOf(to)];
  const moves: Record<string, string> =
    start < RENAMED_IN && target >= RENAMED_IN
      ? { "guide/setup.md": "guide/install.md" }
      : start >= RENAMED_IN && target < RENAMED_IN
        ? { "guide/install.md": "guide/setup.md" }
        : {};
  const moved = moves[path];
  return moved
    ? {
        library: "/fixture/docs-repo",
        ref: to,
        from_ref: from,
        old_path: path,
        new_path: moved,
        similarity: 90,
      }
    : null;
}

interface Served {
  /** Status of the rename lookups. */
  renames?: number;
  /** Status of pinning and unpinning the default. */
  pin?: number;
  /** Holds the rename answers for a ref back until the gate is released. */
  hold?: Record<string, Promise<void>>;
}

/**
 * The library's API: the rename lookup across versions (`guide/setup.md` of v1.3.0 became
 * `guide/install.md` in v1.4.0) and the default-version pin.
 */
function serve({ renames = 200, pin = 200, hold = {} }: Served = {}) {
  const json = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    const { pathname, searchParams: q } = new URL(url, "http://test");
    if (pathname.endsWith("/default-version")) {
      return json(pin, pin === 200 ? {} : { error: "not_found", detail: "gone" });
    }
    await hold[q.get("ref") ?? ""];
    const renamed = renamedPath(q.get("from") ?? "", q.get("ref") ?? "", q.get("path") ?? "");
    return json(renames, renames === 200 ? { renamed } : {});
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

/** The calls that pinned or unpinned the default. */
const pinCalls = (fetch: ReturnType<typeof serve>) =>
  fetch.mock.calls.filter(([url]) => url.endsWith("/default-version"));

/** A promise held open until `release` is called. */
function gate() {
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { held, release };
}

/** Whether the default (v1.4.0) is pinned by an owner. */
let pinned = false;

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
        pinned={pinned}
        keep={{ path }}
      />
      <output aria-label="Showing">
        {ref} {path ?? "(root)"}
      </output>
      {/* Any other link on the page, like an article in the sidebar. */}
      <Link
        to="/libraries/$owner/$repo"
        params={{ owner: "fixture", repo: "docs-repo" }}
        search={{ version: ref, path: "guide/auth.md" }}
      >
        Auth guide
      </Link>
    </>
  );
}

function view(start: string, options: { pinned?: boolean } = {}) {
  pinned = options.pinned ?? false;
  // Like the app's client: failed queries are retried, so a lookup that is retried shows up as a wait.
  const client = new QueryClient({ defaultOptions: { queries: { retry: 2 } } });
  render(
    <QueryClientProvider client={client}>
      <TestRouter pages={{ "/": Page, "/libraries/$owner/$repo": Page }} start={start} />
    </QueryClientProvider>,
  );
  return client;
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

const byRef = (ref: string) => versions.find((v) => v.ref === ref) ?? version(ref, "0");

/** The state of the answer for the open article (`guide/setup.md`) from `from` to `to`. */
const answered = (client: QueryClient, from: string, to: string) =>
  client.getQueryState(
    pathInVersionQueryOptions("fixture", "docs-repo", byRef(from), byRef(to), "guide/setup.md")
      .queryKey,
  )?.status;

const trigger = () => screen.getByRole("button", { name: /Change version/ });

/** Lets a late navigation happen, if one is coming, before checking that none did. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 50));

const showing = () => screen.findByRole("status", { name: "Showing" });

afterEach(() => vi.unstubAllGlobals());

describe("VersionPicker follows renames", () => {
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

  it("opens the renamed article when switching past the version that renamed it (#201)", async () => {
    serve();
    view("/libraries/fixture/docs-repo?version=v1.2.0&path=guide%2Fsetup.md");
    await switchTo("v1.4.0");
    expect(await showing()).toHaveTextContent("v1.4.0 guide/install.md");
  });

  it("follows the rename back past the version that renamed it", async () => {
    serve();
    view("/libraries/fixture/docs-repo?version=v1.4.0&path=guide%2Finstall.md");
    await switchTo("v1.2.0");
    expect(await showing()).toHaveTextContent("v1.2.0 guide/setup.md");
  });

  it("asks the server once per version it may switch to", async () => {
    const fetch = serve();
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await openPicker();
    await waitFor(() =>
      expect(linkTo("v1.4.0")).toHaveAttribute("href", expect.stringContaining("install")),
    );
    const asked = fetch.mock.calls.map(([url]) => new URL(url, "http://test").searchParams);
    expect(asked.map((q) => [q.get("from"), q.get("ref"), q.get("path")]).sort()).toEqual([
      ["v1.3.0", "v1.2.0", "guide/setup.md"],
      ["v1.3.0", "v1.4.0", "guide/setup.md"],
    ]);
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
    serve({ renames: 404 });
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
    serve({ renames: 503 });
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
    serve({ hold: { "v1.4.0": slow.held, "v1.2.0": fast.held } });
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
    await settle();
    expect(await showing()).toHaveTextContent("v1.2.0 guide/setup.md");
  });

  it("does not switch late when the user went elsewhere while waiting", async () => {
    const slow = gate();
    serve({ hold: { "v1.4.0": slow.held } });
    const client = view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await openPicker();
    // v1.2.0 has its answer: a plain link, followed at once while v1.4.0 still waits.
    await waitFor(() => expect(answered(client, "v1.3.0", "v1.2.0")).toBe("success"));
    await userEvent.click(linkTo("v1.4.0"));
    await switchTo("v1.2.0");
    expect(await screen.findByText("v1.2.0 guide/setup.md")).toBeInTheDocument();
    slow.release();
    await settle();
    expect(await showing()).toHaveTextContent("v1.2.0 guide/setup.md");
  });

  it("stays on a page the user opened while a switch waited", async () => {
    const slow = gate();
    serve({ hold: { "v1.4.0": slow.held } });
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await switchTo("v1.4.0");
    expect(trigger()).toHaveAttribute("aria-busy", "true");

    await userEvent.click(screen.getByRole("link", { name: "Auth guide" }));
    expect(await showing()).toHaveTextContent("v1.3.0 guide/auth.md");
    // The wait is over for the user at once: no spinner on the page they went to.
    expect(trigger()).not.toHaveAttribute("aria-busy");

    slow.release();
    await settle();
    expect(await showing()).toHaveTextContent("v1.3.0 guide/auth.md");
  });

  it("drops a waiting switch when the current version is chosen instead", async () => {
    const slow = gate();
    serve({ hold: { "v1.4.0": slow.held } });
    view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await switchTo("v1.4.0");
    expect(trigger()).toHaveAttribute("aria-busy", "true");

    await switchTo("v1.3.0");
    await waitFor(() => expect(trigger()).not.toHaveAttribute("aria-busy"));

    slow.release();
    await settle();
    expect(await showing()).toHaveTextContent("v1.3.0 guide/setup.md");
  });

  it("shows the version it switches to without the current version's labels", async () => {
    const slow = gate();
    serve({ hold: { "v1.3.0": slow.held } });
    view("/libraries/fixture/docs-repo?version=v1.4.0&path=guide%2Finstall.md");
    expect(await screen.findByRole("button", { name: /Change version/ })).toHaveTextContent(
      "default",
    );
    await switchTo("v1.3.0");

    expect(trigger()).toHaveTextContent("v1.3.0");
    expect(trigger()).toHaveTextContent("a".repeat(7));
    expect(trigger()).not.toHaveTextContent("default");
    expect(trigger()).not.toHaveTextContent("b".repeat(7));
    slow.release();
    expect(await showing()).toHaveTextContent("v1.3.0 guide/setup.md");
  });

  it("asks again, the next time the list opens, after a lookup that timed out", async () => {
    let stalled = false;
    const fetch = serve();
    const answer = fetch.getMockImplementation();
    // The first lookup on v1.4.0 stalls until it times out; later ones answer.
    fetch.mockImplementation((url: string, init?: RequestInit) => {
      const ref = new URL(url, "http://test").searchParams.get("ref");
      if (ref !== "v1.4.0" || stalled) return answer?.(url, init) ?? Promise.reject();
      stalled = true;
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      });
    });
    const client = view("/libraries/fixture/docs-repo?version=v1.3.0&path=guide%2Fsetup.md");
    await openPicker();
    await waitFor(() => expect(answered(client, "v1.3.0", "v1.4.0")).toBe("success"), {
      timeout: RENAME_LOOKUP_TIMEOUT_MS * 2,
    });
    expect(linkTo("v1.4.0")).toHaveAttribute(
      "href",
      expect.stringContaining("path=guide%2Fsetup.md"),
    );

    await userEvent.keyboard("{Escape}");
    await openPicker();
    await waitFor(() =>
      expect(linkTo("v1.4.0")).toHaveAttribute(
        "href",
        expect.stringContaining("path=guide%2Finstall.md"),
      ),
    );
  });
});

describe("VersionPicker default pin", () => {
  const lib = "/fixture/docs-repo";

  it("pins the shown version as the default and reloads what shows the default", async () => {
    const fetch = serve();
    const client = view(`/libraries${lib}?version=v1.3.0`);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await openPicker();
    expect(screen.queryByRole("button", { name: /Unpin default/ })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Pin v1.3.0 as default" }));

    await waitFor(() => expect(pinCalls(fetch)).toHaveLength(1));
    const [url, init] = pinCalls(fetch)[0] ?? [];
    expect(url).toBe(`/api/v1/libraries${lib}/default-version`);
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ ref: "v1.3.0" });
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: BROWSE_KEY }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: LIBRARIES_KEY });
  });

  it("marks a pinned default and offers only to unpin it", async () => {
    const fetch = serve();
    view(`/libraries${lib}?version=v1.4.0`, { pinned: true });
    await openPicker();

    expect(screen.getAllByText("pinned default")).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: /as default/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Unpin default/ }));

    await waitFor(() => expect(pinCalls(fetch)).toHaveLength(1));
    const [url, init] = pinCalls(fetch)[0] ?? [];
    expect(url).toBe(`/api/v1/libraries${lib}/default-version`);
    expect(init?.method).toBe("DELETE");
  });

  it("says so when the version or library is gone", async () => {
    serve({ pin: 404 });
    view(`/libraries${lib}?version=v1.3.0`);
    await openPicker();
    await userEvent.click(screen.getByRole("button", { name: "Pin v1.3.0 as default" }));

    expect(await screen.findByText(/version or library is no longer imported/)).toBeInTheDocument();
  });

  it("pins with an article open and still follows its rename to the pinned default", async () => {
    const fetch = serve();
    view(`/libraries${lib}?version=v1.3.0&path=guide%2Fsetup.md`, { pinned: true });
    await openPicker();
    expect(linkTo("v1.4.0")).toHaveTextContent("pinned default");
    await waitFor(() =>
      expect(linkTo("v1.4.0")).toHaveAttribute(
        "href",
        expect.stringContaining("path=guide%2Finstall.md"),
      ),
    );

    await userEvent.click(screen.getByRole("button", { name: "Pin v1.3.0 as default" }));
    await waitFor(() => expect(pinCalls(fetch)).toHaveLength(1));
    expect(pinCalls(fetch)[0]?.[1]?.method).toBe("PUT");
    // Pinning reloads the browse queries, the rename answers among them: the link keeps its path.
    expect(linkTo("v1.4.0")).toHaveAttribute(
      "href",
      expect.stringContaining("path=guide%2Finstall.md"),
    );

    await userEvent.click(linkTo("v1.4.0"));
    expect(await showing()).toHaveTextContent("v1.4.0 guide/install.md");
  });
});
