import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAppRouter } from "./router";

const json = (body: unknown) => Response.json(body);
const signedIn = { state: "signed_in", account: { id: "1", username: "ada", role: "viewer" } };

function mount(path: string, session: unknown, health: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      json(
        url.endsWith("/health") ? health : url.endsWith("/libraries") ? { libraries: [] } : session,
      ),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createAppRouter(client, createMemoryHistory({ initialEntries: [path] }));
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("the footer", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the version the server reports, under an app page", async () => {
    mount("/", signedIn, { status: "ok", version: "0.9.3" });
    const footer = await screen.findByRole("contentinfo");
    expect(await within(footer).findByText("0.9.3")).toBeInTheDocument();
    expect(within(footer).getByRole("link", { name: "Connect an agent" })).toHaveAttribute(
      "href",
      "/account",
    );
    expect(within(footer).getByRole("link", { name: "OpenAPI" })).toHaveAttribute(
      "href",
      "/api/v1/openapi.json",
    );
    for (const link of within(footer).getAllByRole("link")) {
      if (link.getAttribute("target") === "_blank") {
        expect(link.getAttribute("rel")).toContain("noopener");
      }
    }
    const away = within(footer).getAllByRole("link", { name: /opens a new tab/ });
    expect(away.map((a) => a.getAttribute("href"))).toEqual([
      "https://sircypkowskyy.github.io/ExactDocs/",
      "https://sircypkowskyy.github.io/ExactDocs/rest-api/",
      "https://github.com/SirCypkowskyy/ExactDocs",
      "https://github.com/SirCypkowskyy/ExactDocs/blob/main/LICENSE",
    ]);
    for (const a of away) expect(a).toHaveAttribute("target", "_blank");
  });

  it("is on the sign-in page too, without a version it was not told or the account's link", async () => {
    mount("/sign-in", { state: "signed_out" }, { status: "ok" });
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByText("ExactDocs")).toBeInTheDocument();
    expect(within(footer).queryByRole("link", { name: "Connect an agent" })).toBeNull();
    expect(within(footer).queryByText(/^\d+\.\d+\.\d+/)).toBeNull();
  });

  it("is on the not-found page", async () => {
    mount("/nothing/here", signedIn, { status: "ok", version: "0.9.3" });
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });
});
