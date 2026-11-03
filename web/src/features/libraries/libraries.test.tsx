import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LibrariesPage } from "./index";

describe("libraries slice", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders indexed libraries with their versions", async () => {
    const fetchMock = vi.fn(async () =>
      Response.json({ libraries: [{ name: "react", versions: ["19.1"] }] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <Suspense fallback="loading">
          <LibrariesPage />
        </Suspense>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("react")).toBeInTheDocument();
    expect(screen.getByText("19.1")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/libraries", expect.anything());
  });
});
