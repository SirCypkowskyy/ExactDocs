import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "./preferences";
import { usePhoneLayout } from "./use-media-query";

describe("the phone layout follows the text size (#576)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    act(() => resetPreferences());
  });

  it("moves the breakpoint with the text size, like the md: variant", () => {
    // A 1000 px window: wider than 48rem (768 px), narrower than 72rem (1152 px).
    const queries: string[] = [];
    vi.stubGlobal("matchMedia", (query: string) => {
      queries.push(query);
      const max = Number(/max-width: ([\d.]+)rem/.exec(query)?.[1]);
      return {
        matches: 1000 <= max * 16,
        addEventListener: () => {},
        removeEventListener: () => {},
      };
    });
    const { result } = renderHook(() => usePhoneLayout());
    expect(result.current).toBe(false);
    expect(queries).toContain("(max-width: 47.99rem)");

    act(() => setPreferences({ text_scale: 150 }));
    expect(result.current).toBe(true);
    expect(queries).toContain("(max-width: 71.99rem)");
  });
});
