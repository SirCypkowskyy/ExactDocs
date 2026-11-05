import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BROWSE_KEY } from "@/shared/lib/query-keys";
import { TagEditor } from "./tag-editor";

const article = {
  path: "guide/install.md",
  tags: ["guide", "setup", "onboarding", "legacy"],
  front_matter: { tags: ["setup"] },
  manual_tags: [
    { tag: "onboarding", path: "guide/install.md" },
    { tag: "legacy", path: "old/install.md" },
  ],
};

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
    const sent = serve((s) =>
      Response.json({ library: "/acme/payments", path: "guide/install.md", tags: s.body }),
    );
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
    expect(sent[0]?.body).toEqual({ tags: ["onboarding", "getting-started"] });
    await waitFor(() => expect(client.getQueryState(other)?.isInvalidated).toBe(true));
    expect(client.getQueryState(everywhere)?.isInvalidated).toBe(true);
    expect(client.getQueryState(unrelated)?.isInvalidated).toBe(false);
    expect(screen.getByRole("textbox", { name: "New tag" })).toHaveValue("");
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
    const sent = serve((s) =>
      Response.json({ library: "/acme/payments", path: "x", tags: s.body }),
    );
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
    serve((s) => Response.json({ library: "/acme/payments", path: "x", tags: s.body }));
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

  it("says that the front matter declares a manual tag too, and that a removed one stays when imported", async () => {
    serve();
    const shown = {
      ...article,
      tags: ["guide"],
      manual_tags: [{ tag: "guide", path: "guide/install.md" }],
    };
    const client = mount(new QueryClient(), { ...shown, front_matter: { tags: ["guide"] } });
    const byHand = screen.getByRole("list", { name: "Tags added by hand" });
    expect(within(byHand).getByText("also in front matter")).toBeVisible();
    // A tag set by hand is listed once, under "by hand", whatever else gives it.
    expect(screen.queryByRole("list", { name: "Tags from path rules" })).toBeNull();
    client.show(shown);
    await userEvent.click(screen.getByRole("button", { name: "Remove tag guide" }));
    client.show({ ...shown, manual_tags: [] });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "guide stays on this article: its import gives it too.",
    );
    expect(screen.getByRole("list", { name: "Tags from path rules" })).toHaveTextContent("guide");
  });
});
