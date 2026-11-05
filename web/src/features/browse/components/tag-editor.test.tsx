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

function mount(client = new QueryClient()) {
  render(
    <QueryClientProvider client={client}>
      <TagEditor owner="acme" repo="payments" article={article} />
    </QueryClientProvider>,
  );
  return client;
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

  it("adds a tag to the path's manual tags and reloads the browse queries of every version", async () => {
    const sent = serve((s) =>
      Response.json({ library: "/acme/payments", path: "guide/install.md", tags: s.body }),
    );
    const client = mount();
    const other = [...BROWSE_KEY, "acme", "payments", "v1.0.0", "sha", "tags"];
    client.setQueryData(other, { tags: [], truncated: false });
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
    render(
      <QueryClientProvider client={new QueryClient()}>
        <TagEditor
          owner="acme"
          repo="payments"
          article={{
            ...article,
            manual_tags: [
              { tag: "a", path: "guide/install.md" },
              { tag: "b", path: "guide/install.md" },
            ],
          }}
        />
      </QueryClientProvider>,
    );
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
    await userEvent.type(input, "onboarding{Enter}");
    expect(screen.getByRole("status")).toHaveTextContent(/already has that tag/);
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
  });
});
