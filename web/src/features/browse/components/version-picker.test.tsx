import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BROWSE_KEY, LIBRARIES_KEY } from "@/shared/lib/query-keys";
import { TestRouter } from "@/shared/lib/test-router";
import type { Version } from "../model/browse";
import { VersionPicker } from "./version-picker";

const v = (ref: string, is_default = false) =>
  ({
    ref,
    kind: "tag",
    commit_sha: "a".repeat(40),
    imported_at: "2026-11-01T10:00:00Z",
    is_default,
  }) as Version;

let client: QueryClient;
let props: { current: Version; pinned: boolean; versions: Version[] };

function Page() {
  return (
    <QueryClientProvider client={client}>
      <VersionPicker owner="acme" repo="payments" keep={{}} {...props} />
    </QueryClientProvider>
  );
}

function view(current: Version, pinned: boolean, versions = [v("v1.5.0", !pinned), current]) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  props = { current, pinned, versions };
  render(<TestRouter pages={{ "/": Page }} />);
}

function serve(status = 200) {
  const fetch = vi.fn((_url: string, _init?: RequestInit) =>
    Promise.resolve(
      new Response(JSON.stringify(status === 200 ? {} : { error: "not_found", detail: "gone" }), {
        status,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => vi.unstubAllGlobals());

describe("VersionPicker default pin", () => {
  it("pins the shown version as the default and reloads what shows the default", async () => {
    const fetch = serve();
    view(v("v1.3.0"), false);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await userEvent.click(await screen.findByRole("button", { name: /Change version/ }));
    expect(screen.queryByRole("button", { name: /Unpin default/ })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Pin v1.3.0 as default" }));

    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/libraries/acme/payments/default-version");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ ref: "v1.3.0" });
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: BROWSE_KEY }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: LIBRARIES_KEY });
  });

  it("marks a pinned default and offers only to unpin it", async () => {
    const fetch = serve();
    const pinned = v("v1.3.0", true);
    view(pinned, true, [v("v1.5.0"), pinned]);
    await userEvent.click(await screen.findByRole("button", { name: /Change version/ }));

    expect(screen.getAllByText("pinned default")).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: /as default/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Unpin default/ }));

    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/libraries/acme/payments/default-version");
    expect(init?.method).toBe("DELETE");
  });

  it("says so when the version is gone", async () => {
    serve(404);
    view(v("v1.3.0"), false);
    await userEvent.click(await screen.findByRole("button", { name: /Change version/ }));
    await userEvent.click(screen.getByRole("button", { name: "Pin v1.3.0 as default" }));

    expect(await screen.findByText(/no longer imported/)).toBeInTheDocument();
  });
});
