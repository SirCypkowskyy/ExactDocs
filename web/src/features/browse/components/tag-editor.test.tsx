import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BROWSE_KEY } from "@/shared/lib/query-keys";
import { TagEditor } from "./tag-editor";

type Origin = "front_matter" | "path_rule" | "imported" | "manual";

const article = {
  path: "guide/install.md",
  tags: ["guide", "setup", "onboarding", "legacy"],
  tag_origins: [
    { tag: "guide", origins: ["path_rule"] },
    { tag: "setup", origins: ["front_matter"] },
    { tag: "onboarding", origins: ["manual"] },
    { tag: "legacy", origins: ["manual"] },
  ] as { tag: string; origins: Origin[] }[],
  manual_tags: [
    { tag: "onboarding", path: "guide/install.md" },
    { tag: "legacy", path: "old/install.md" },
  ],
};

/** The server's answer to a change of manual tags: what it stored (deduplicated), or nothing. */
const stored = (s: Sent, made: (tag: string) => string = (t) => t) =>
  s.method === "DELETE"
    ? new Response(null, { status: 204 })
    : Response.json({
        library: "/acme/payments",
        path: s.url.searchParams.get("path"),
        tags: [...new Set((s.body as { tags: string[] }).tags.map(made))],
      });
/** Roughly what the server does to a tag, enough for these tests. */
const made = (tag: string) => tag.toLowerCase().split(/\s+/).join("-");

interface Sent {
  method: string;
  url: URL;
  body: unknown;
}

function serve(answer: (sent: Sent) => Response = () => new Response(null, { status: 204 })) {
  const sent: Sent[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const one = {
        method: init?.method ?? "GET",
        url: new URL(input, "http://x"),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      };
      sent.push(one);
      return answer(one);
    }),
  );
  return sent;
}

type Shown = typeof article & { manual_tags: { tag: string; path: string }[] };

function mount(client = new QueryClient(), shown: Shown = article) {
  const page = (a: Shown) => (
    <QueryClientProvider client={client}>
      <TagEditor owner="acme" repo="payments" article={a} />
    </QueryClientProvider>
  );
  const { rerender } = render(page(shown));
  return Object.assign(client, { show: (a: Shown) => rerender(page(a)) });
}

afterEach(() => vi.unstubAllGlobals());

describe("TagEditor", () => {
  it("shows each tag under where it comes from", () => {
    serve();
    mount();
    expect(screen.getByRole("list", { name: "Tags from front matter" })).toHaveTextContent("setup");
    expect(screen.getByRole("list", { name: "Tags from path rules" })).toHaveTextContent(/^guide$/);
    const byHand = screen.getByRole("list", { name: "Tags added by hand" });
    expect(within(byHand).getByText("onboarding")).toBeVisible();
    expect(within(byHand).getByText("old/install.md")).toBeVisible();
    // Imported tags cannot be removed here: only the manual ones have a button.
    expect(screen.getAllByRole("button", { name: /^Remove tag/ })).toHaveLength(2);
  });

  it("adds a tag to the path's manual tags and reloads the library's browse queries of every version", async () => {
    const sent = serve((s) => stored(s, made));
    const client = mount();
    const other = [...BROWSE_KEY, "acme", "payments", "v1.0.0", "sha", "tags"];
    const unrelated = [...BROWSE_KEY, "acme", "billing", "v1.0.0", "sha", "tags"];
    const everywhere = [...BROWSE_KEY, "*search-all*", "retries", ""];
    for (const key of [other, unrelated, everywhere]) client.setQueryData(key, { tags: [] });
    await userEvent.click(screen.getByRole("button", { name: "Add tag" }));
    await userEvent.type(
      screen.getByRole("textbox", { name: "New tag" }),
      "Getting Started{Enter}",
    );
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.method).toBe("PUT");
    expect(sent[0]?.url.pathname).toBe("/api/v1/libraries/acme/payments/tags");
    expect(sent[0]?.url.searchParams.get("path")).toBe("guide/install.md");
    // Sent as typed: the server makes the tag.
    expect(sent[0]?.body).toEqual({ tags: ["onboarding", "Getting Started"] });
    await waitFor(() => expect(client.getQueryState(other)?.isInvalidated).toBe(true));
    expect(client.getQueryState(everywhere)?.isInvalidated).toBe(true);
    expect(client.getQueryState(unrelated)?.isInvalidated).toBe(false);
    expect(screen.getByRole("textbox", { name: "New tag" })).toHaveValue("");
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("says so when the server makes what was typed into a tag the path already had", async () => {
    serve((s) => stored(s, made));
    mount(new QueryClient(), {
      ...article,
      tags: [...article.tags, "getting-started"],
      manual_tags: [...article.manual_tags, { tag: "getting-started", path: "guide/install.md" }],
    });
    await userEvent.click(screen.getByRole("button", { name: "Add tag" }));
    await userEvent.type(
      screen.getByRole("textbox", { name: "New tag" }),
      "Getting  Started{Enter}",
    );
    expect(await screen.findByText(/already has that tag/)).toBeVisible();
  });

  it("removes an inherited tag on the path it was set on, with DELETE when none is left", async () => {
    const sent = serve();
    mount();
    await userEvent.click(
      screen.getByRole("button", { name: "Remove tag legacy, set on old/install.md" }),
    );
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.method).toBe("DELETE");
    expect(sent[0]?.url.searchParams.get("path")).toBe("old/install.md");
  });

  it("removes one of the path's own tags with PUT of the rest", async () => {
    const sent = serve((s) => stored(s));
    mount(new QueryClient(), {
      ...article,
      manual_tags: [
        { tag: "a", path: "guide/install.md" },
        { tag: "b", path: "guide/install.md" },
      ],
    });
    await userEvent.click(screen.getByRole("button", { name: "Remove tag a" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ method: "PUT", body: { tags: ["b"] } });
  });

  it("refuses what cannot be a tag without asking the server, and says why", async () => {
    const sent = serve();
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Add tag" }));
    const input = screen.getByRole("textbox", { name: "New tag" });
    await userEvent.type(input, "#nope{Enter}");
    expect(screen.getByRole("status")).toHaveTextContent(/starts with a letter or digit/);
    expect(input).toHaveAttribute("aria-invalid", "true");
    await userEvent.clear(input);
    // The server keeps 40 characters at most.
    await userEvent.clear(input);
    await userEvent.type(input, `${"x".repeat(41)}{Enter}`);
    expect(screen.getByRole("status")).toHaveTextContent(/40 characters at most/);
    // Already on the article: set by hand here, inherited from an older path, or imported.
    for (const tag of ["onboarding", "legacy", "guide"]) {
      await userEvent.clear(input);
      await userEvent.type(input, `${tag}{Enter}`);
      expect(screen.getByRole("status")).toHaveTextContent(/already has that tag/);
    }
    // The reason is read with the field.
    const status = screen.getByRole("status");
    expect(input.getAttribute("aria-describedby")?.split(" ")).toContain(status.id);
    expect(sent).toHaveLength(0);
  });

  it("says when the server refuses, and closes the field with Escape", async () => {
    serve(() =>
      Response.json({ error: "invalid_tags", detail: "not a tag", fields: [] }, { status: 422 }),
    );
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Add tag" }));
    await userEvent.type(screen.getByRole("textbox", { name: "New tag" }), "fine{Enter}");
    expect(await screen.findByText(/starts with a letter or digit/)).toBeVisible();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("textbox", { name: "New tag" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("");
    // Focus goes back where the field was opened from, not to the top of the page.
    expect(screen.getByRole("button", { name: "Add tag" })).toHaveFocus();
  });

  it("returns focus to Add tag when the field is cancelled", async () => {
    serve();
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Add tag" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Add tag" })).toHaveFocus();
  });

  it("moves focus to the next tag's remove button after a removal, else to Add tag", async () => {
    serve((s) => stored(s));
    const client = mount();
    await userEvent.click(screen.getByRole("button", { name: "Remove tag onboarding" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Remove tag legacy, set on old/install.md" }),
      ).toHaveFocus(),
    );
    // The reload drops the removed chip; then the last one goes too.
    client.show({ ...article, manual_tags: [{ tag: "legacy", path: "old/install.md" }] });
    await userEvent.click(
      screen.getByRole("button", { name: "Remove tag legacy, set on old/install.md" }),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Add tag" })).toHaveFocus());
  });

  it("shows a tag with several origins under each, and that a removed one stays when imported", async () => {
    serve();
    const shown = {
      ...article,
      tags: ["guide"],
      tag_origins: [{ tag: "guide", origins: ["front_matter", "path_rule", "manual"] as Origin[] }],
      manual_tags: [{ tag: "guide", path: "guide/install.md" }],
    };
    const client = mount(new QueryClient(), shown);
    expect(screen.getByRole("list", { name: "Tags from front matter" })).toHaveTextContent("guide");
    expect(screen.getByRole("list", { name: "Tags from path rules" })).toHaveTextContent("guide");
    const byHand = screen.getByRole("list", { name: "Tags added by hand" });
    expect(within(byHand).getByText("guide")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Remove tag guide" }));
    const imported = { tag: "guide", origins: ["front_matter", "path_rule"] as Origin[] };
    client.show({ ...shown, tag_origins: [imported], manual_tags: [] });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "guide stays on this article: its import gives it too.",
    );
    expect(screen.getByRole("list", { name: "Tags from path rules" })).toHaveTextContent("guide");
  });

  it("lists imported tags of an older version apart, as their origin was not recorded", () => {
    serve();
    mount(new QueryClient(), {
      ...article,
      tags: ["guide"],
      tag_origins: [{ tag: "guide", origins: ["imported"] }],
      manual_tags: [],
    });
    expect(
      screen.getByRole("list", { name: "Tags from front matter or path rules" }),
    ).toHaveTextContent("guide");
    expect(screen.queryByRole("list", { name: "Tags from path rules" })).toBeNull();
    expect(screen.getByText(/imported before ExactDocs kept which is which/)).toBeVisible();
  });
});
