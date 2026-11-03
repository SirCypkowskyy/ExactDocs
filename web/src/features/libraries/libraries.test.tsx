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
      Response.json({
        libraries: [
          {
            id: "/acme/payments",
            title: "Payments",
            description: "",
            versions: ["main", "v1.4.0"],
            default_version: "v1.4.0",
          },
        ],
      }),
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

    expect(await screen.findByText("/acme/payments")).toBeInTheDocument();
    expect(screen.getByText("v1.4.0")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/libraries", expect.anything());
  });
});
