import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EMPTY_CREDENTIAL } from "@/shared/lib/credentials";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { Button } from "./button";
import { CredentialField } from "./credential-field";
import { FormAlert } from "./form-alert";
import { TagChips } from "./tag-chips";

describe("Button", () => {
  it("keeps its label while pending, says it is busy and still gets the click", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button pending onClick={onClick}>
        Save changes
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Save changes" });
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveAttribute("aria-disabled", "true");
    await user.click(button);
    // The handler decides what a repeat press does (forms ignore it); the button stays focusable.
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("is a plain, idle button otherwise", () => {
    render(<Button>Save changes</Button>);
    const button = screen.getByRole("button", { name: "Save changes" });
    expect(button).not.toHaveAttribute("aria-busy");
    expect(button).toHaveAttribute("type", "button");
  });
});

describe("FormAlert", () => {
  it("keeps its live region mounted so the message is announced when it arrives", () => {
    const { rerender } = render(<FormAlert id="alert" />);
    const region = screen.getByRole("alert");
    expect(region).toBeEmptyDOMElement();
    rerender(<FormAlert id="alert" message="Wrong password." />);
    expect(screen.getByRole("alert")).toBe(region);
    expect(region).toHaveTextContent("Wrong password.");
    rerender(<FormAlert id="alert" />);
    expect(region).toBeEmptyDOMElement();
  });

  it("offers a way out as a link after the message", () => {
    render(<FormAlert id="alert" message="Taken." link={{ href: "/x", label: "Open it" }} />);
    expect(screen.getByRole("link", { name: "Open it" })).toHaveAttribute("href", "/x");
  });
});

function Chips({
  facets = FACETS,
  loading = false,
}: {
  facets?: typeof FACETS;
  loading?: boolean;
}) {
  const [value, setValue] = useState<string | undefined>("api");
  return (
    <TagChips
      facets={facets}
      value={value}
      loading={loading}
      truncated={false}
      onChange={setValue}
    />
  );
}
const FACETS = [
  { tag: "guide", count: 2 },
  { tag: "api", count: 1 },
  { tag: "auth", count: 1 },
];

describe("TagChips", () => {
  it("shows the selected tag first, pressed, and lets each chip be toggled", async () => {
    const user = userEvent.setup();
    render(<Chips />);
    const chips = screen.getAllByRole("button");
    expect(chips[0]).toHaveAccessibleName(/^api/);
    expect(chips[0]).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: /^guide/ }));
    expect(screen.getByRole("button", { name: /^guide/ })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: /^api/ }));
    expect(screen.getByRole("button", { name: /^api/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("renders nothing when the version has no tags", () => {
    const { container } = render(
      <TagChips
        facets={[]}
        value={undefined}
        loading={false}
        truncated={false}
        onChange={vi.fn()}
      />,
    );
    expect(container.querySelector("fieldset")).toBeNull();
  });

  it("shows flat skeleton bars, not buttons, while the counts load", () => {
    render(<Chips loading />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});

describe("shared components in Polish", () => {
  afterEach(() => resetPreferences());

  it("labels the tag filter in Polish and formats counts the Polish way", () => {
    setPreferences({ language: "pl" });
    render(
      <TagChips
        facets={[{ tag: "api", count: 12345 }]}
        value={undefined}
        loading={false}
        truncated
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("group", { name: "Filtruj według tagu" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^api/ })).toHaveTextContent(/12\s345/);
    expect(screen.getByText("Widoczne są tylko najczęściej używane tagi.")).toBeInTheDocument();
  });

  it("names a deploy key field and its file picker in Polish", () => {
    setPreferences({ language: "pl" });
    render(
      <CredentialField id="cred" kind="ssh_key" draft={EMPTY_CREDENTIAL} onChange={vi.fn()} />,
    );
    expect(screen.getByLabelText("Klucz wdrożeniowy")).toHaveAttribute(
      "placeholder",
      "Wklej klucz prywatny",
    );
    expect(screen.getByRole("button", { name: "Wybierz plik klucza" })).toBeInTheDocument();
  });

  it("keeps the English words when English is chosen", () => {
    setPreferences({ language: "en" });
    render(<CredentialField id="cred" kind="token" draft={EMPTY_CREDENTIAL} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Access token")).toHaveAttribute("placeholder", "Paste the token");
    expect(screen.getByLabelText("User name (optional)")).toBeInTheDocument();
  });
});
