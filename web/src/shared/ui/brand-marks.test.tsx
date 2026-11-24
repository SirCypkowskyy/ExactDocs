import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { isBrandIcon, ProviderMark } from "./brand-marks";

const markOf = (container: HTMLElement) => container.firstElementChild as Element;

describe("ProviderMark", () => {
  it.each(["google", "microsoft", "discord", "github"])("draws the %s mark inline", (icon) => {
    const { container } = render(<ProviderMark icon={icon} />);
    const svg = markOf(container);
    expect(svg.tagName.toLowerCase()).toBe("svg");
    expect(svg).toHaveAttribute("data-brand", icon);
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("focusable", "false");
    expect(svg).toHaveClass("size-4");
    // No remote loads: everything is in the page.
    expect(container.querySelector("img, use, image")).toBeNull();
  });

  it("keeps Google's and Microsoft's colours, and draws GitHub and Discord in the text colour", () => {
    const google = render(<ProviderMark icon="google" />).container;
    expect([...google.querySelectorAll("path")].map((p) => p.getAttribute("fill"))).toEqual([
      "#EA4335",
      "#4285F4",
      "#FBBC05",
      "#34A853",
    ]);
    const microsoft = render(<ProviderMark icon="microsoft" />).container;
    expect([...microsoft.querySelectorAll("rect")].map((r) => r.getAttribute("fill"))).toEqual([
      "#F25022",
      "#7FBA00",
      "#00A4EF",
      "#FFB900",
    ]);
    for (const icon of ["github", "discord"]) {
      expect(markOf(render(<ProviderMark icon={icon} />).container)).toHaveAttribute(
        "fill",
        "currentColor",
      );
    }
  });

  it("shows an operator's icon from this server, fitted and silent", () => {
    const { container } = render(
      <ProviderMark iconUrl="/api/v1/auth/corp/icon?v=3" size="md" />,
    );
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("src", "/api/v1/auth/corp/icon?v=3");
    expect(img).toHaveAttribute("alt", "");
    expect(img).toHaveAttribute("width", "20");
    expect(img).toHaveAttribute("height", "20");
    expect(img).toHaveClass("object-contain", "size-5");
  });

  it("prefers the built-in mark over an icon URL", () => {
    const { container } = render(<ProviderMark icon="github" iconUrl="/api/v1/auth/gh/icon" />);
    expect(container.querySelector("img")).toBeNull();
    expect(markOf(container)).toHaveAttribute("data-brand", "github");
  });

  it.each([
    "https://evil.example/icon.png",
    "//evil.example/icon.png",
    "/\\evil.example/icon.png",
    "javascript:alert(1)",
  ])("never loads an icon from elsewhere (%s): a key instead", (url) => {
    const { container } = render(<ProviderMark iconUrl={url} />);
    expect(container.querySelector("img")).toBeNull();
    expect(markOf(container)).toHaveClass("lucide-key-round");
  });

  it("falls back to a key when the icon does not load", () => {
    const { container } = render(<ProviderMark iconUrl="/api/v1/auth/corp/icon?v=1" />);
    fireEvent.error(container.querySelector("img") as HTMLImageElement);
    expect(container.querySelector("img")).toBeNull();
    expect(markOf(container)).toHaveClass("lucide-key-round");
    expect(markOf(container)).toHaveAttribute("aria-hidden", "true");
  });

  it("shows a key for a provider with no mark at all, or an icon name it does not know", () => {
    expect(markOf(render(<ProviderMark />).container)).toHaveClass("lucide-key-round");
    expect(markOf(render(<ProviderMark icon="toString" />).container)).toHaveClass(
      "lucide-key-round",
    );
    expect(isBrandIcon("toString")).toBe(false);
    expect(isBrandIcon("google")).toBe(true);
  });
});
