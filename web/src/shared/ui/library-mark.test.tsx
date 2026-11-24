import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { readPreferences, resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { InterfaceMenu } from "./interface-controls";
import { LibraryMark, libraryLogoUrl } from "./library-mark";
import { TooltipProvider } from "./tooltip";

const LOGO = "0123456789abcdef";
const URL = `/api/v1/libraries/acme/payments/logo?v=${LOGO}`;

describe("LibraryMark", () => {
  afterEach(() => resetPreferences());

  it("asks this server for the logo, versioned so a new logo is a new URL", () => {
    expect(libraryLogoUrl("/acme/payments", LOGO)).toBe(URL);
    expect(libraryLogoUrl("/acme corp/pay#ments", "ab")).toBe(
      "/api/v1/libraries/acme%20corp/pay%23ments/logo?v=ab",
    );
  });

  it("shows the library's logo as decoration on the white tile, in a box of fixed size", () => {
    const { container } = render(<LibraryMark id="/acme/payments" logo={LOGO} size="lg" />);
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("src", URL);
    expect(img).toHaveAttribute("alt", "");
    expect(img).toHaveAttribute("loading", "lazy");
    expect(img).toHaveAttribute("decoding", "async");
    const tile = img?.parentElement;
    expect(tile).toHaveAttribute("aria-hidden", "true");
    // The box is sized before the image arrives: nothing shifts while it loads.
    expect(tile).toHaveClass("size-9", "bg-logo-tile", "border-logo-tile-edge");
  });

  it("shows a generic icon on the library's line colour when it has no logo", () => {
    const { container } = render(<LibraryMark id="/acme/payments" logo={null} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.firstElementChild?.className).toMatch(/bg-line-\d/);
    expect(container).toHaveTextContent("");
  });

  it("falls back to the generic icon when the image does not load, never a broken image", () => {
    const { container } = render(<LibraryMark id="/acme/payments" logo={LOGO} />);
    fireEvent.error(container.querySelector("img") as HTMLImageElement);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("keeps the coloured monogram when logos are turned off, logo or not", () => {
    setPreferences({ library_logos: false });
    const { container } = render(
      <>
        <LibraryMark id="/acme/payments" logo={LOGO} />
        <LibraryMark id="/acme/docs-repo" />
      </>,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
    expect(container).toHaveTextContent("PADR");
  });

  it("follows the preference live", () => {
    const { container } = render(<LibraryMark id="/acme/payments" logo={LOGO} />);
    expect(container.querySelector("img")).not.toBeNull();
    act(() => setPreferences({ library_logos: false }));
    expect(container.querySelector("img")).toBeNull();
    expect(container).toHaveTextContent("PA");
    act(() => setPreferences({ library_logos: true }));
    expect(container.querySelector("img")).toHaveAttribute("src", URL);
  });

  it("is switched off and on from the band's interface menu", async () => {
    render(
      <TooltipProvider>
        <TestRouter
          pages={{
            "/": () => (
              <>
                <InterfaceMenu />
                <LibraryMark id="/acme/payments" logo={LOGO} />
              </>
            ),
            "/account": () => null,
          }}
        />
      </TooltipProvider>,
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Interface and accessibility" }));
    const toggle = await screen.findByRole("menuitemcheckbox", { name: "Library logos" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    await user.click(toggle);
    expect(readPreferences().library_logos).toBe(false);
    expect(document.querySelector("img")).toBeNull();
  });

  it("names the switch in Polish", async () => {
    setPreferences({ language: "pl" });
    render(
      <TooltipProvider>
        <TestRouter pages={{ "/": () => <InterfaceMenu />, "/account": () => null }} />
      </TooltipProvider>,
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Interfejs i dostępność" }));
    expect(
      await screen.findByRole("menuitemcheckbox", { name: "Logo bibliotek" }),
    ).toBeInTheDocument();
  });
});
