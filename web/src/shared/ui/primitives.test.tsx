import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ArrowRight, MoreHorizontal, Plus } from "lucide-react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EMPTY_CREDENTIAL } from "@/shared/lib/credentials";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "./alert-dialog";
import { Avatar, initials } from "./avatar";
import { Badge } from "./badge";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "./breadcrumb";
import { Button, IconButton } from "./button";
import { CredentialField } from "./credential-field";
import { StateBadge } from "./data-table/cells";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./dropdown-menu";
import { FormAlert } from "./form-alert";
import { ThemeButton } from "./interface-controls";
import { LibraryMark } from "./library-mark";
import { Meter } from "./meter";
import { TagChips } from "./tag-chips";
import { ToggleGroup, ToggleGroupItem } from "./toggle-group";

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

  it("nudges its error icon once on arrival, but not a neutral wait", () => {
    const { rerender } = render(<FormAlert id="alert" message="Wrong password." />);
    expect(screen.getByRole("alert").querySelector("svg")).toHaveAttribute(
      "data-icon-motion",
      "alert",
    );
    rerender(<FormAlert id="alert" message="Still importing." tone="info" />);
    expect(screen.getByRole("alert").querySelector("svg")).not.toHaveAttribute("data-icon-motion");
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

describe("IconButton", () => {
  it("is named by its label, and its tooltip says the same with the shortcut", async () => {
    render(
      <IconButton label="Larger text" shortcut="Ctrl +">
        <Plus aria-hidden="true" />
      </IconButton>,
    );
    const button = screen.getByRole("button", { name: "Larger text" });
    await userEvent.tab();
    expect(button).toHaveFocus();
    // Keyboard focus opens the tooltip at once.
    const tip = await screen.findByRole("tooltip");
    expect(tip).toHaveTextContent("Larger text");
    expect(tip).toHaveTextContent("Ctrl +");
  });

  it("puts the asked-for reaction on its icon", () => {
    render(
      <IconButton label="Open" motion="forward">
        <ArrowRight aria-hidden="true" />
      </IconButton>,
    );
    const icon = screen.getByRole("button", { name: "Open" }).querySelector("svg");
    expect(icon).toHaveAttribute("data-icon-motion", "forward");
  });

  it("keeps its name while busy and swaps the icon for the busy mark", () => {
    render(
      <IconButton label="Sync now" pending>
        <ArrowRight aria-hidden="true" />
      </IconButton>,
    );
    const button = screen.getByRole("button", { name: "Sync now" });
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button.querySelector("svg")).toBeNull();
  });

  it("can be a menu's trigger, keeping its name and tooltip", async () => {
    const picked = vi.fn();
    render(
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <IconButton label="More actions">
            <MoreHorizontal aria-hidden="true" />
          </IconButton>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem onSelect={picked}>Copy ID</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>,
    );
    const button = screen.getByRole("button", { name: "More actions" });
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(await screen.findByRole("menuitem", { name: "Copy ID" }));
    expect(picked).toHaveBeenCalledOnce();
    expect(button).toHaveAttribute("aria-expanded", "false");
  });
});

function Confirm({ onConfirm = () => {} }: { onConfirm?: () => void }) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="destructive">Revoke…</Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogTitle>Revoke this token?</AlertDialogTitle>
        <AlertDialogDescription>Agents using it stop at once.</AlertDialogDescription>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>Revoke</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

describe("AlertDialog", () => {
  it("is an alert dialog, named and described, with Cancel focused first", async () => {
    render(<Confirm />);
    await userEvent.click(screen.getByRole("button", { name: "Revoke…" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Revoke this token?" });
    expect(dialog).toHaveAccessibleDescription("Agents using it stop at once.");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("ignores a click outside; Escape cancels and focus goes back to the trigger", async () => {
    render(<Confirm />);
    const trigger = screen.getByRole("button", { name: "Revoke…" });
    await userEvent.click(trigger);
    const dialog = await screen.findByRole("alertdialog");
    const overlay = document.querySelector("[data-slot='alert-dialog-overlay']") as HTMLElement;
    fireEvent.pointerDown(overlay);
    fireEvent.click(overlay);
    expect(dialog).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes when confirmed", async () => {
    const confirmed = vi.fn();
    render(<Confirm onConfirm={confirmed} />);
    await userEvent.click(screen.getByRole("button", { name: "Revoke…" }));
    await userEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    expect(confirmed).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});

describe("reduced motion", () => {
  afterEach(() => {
    resetPreferences();
    vi.unstubAllGlobals();
    Reflect.deleteProperty(document, "startViewTransition");
  });

  /** A browser with view transitions that records each one. */
  function viewTransitions() {
    const started = vi.fn((change: () => void) => {
      change();
      return { finished: Promise.resolve() };
    });
    Object.defineProperty(document, "startViewTransition", { value: started, configurable: true });
    return started;
  }

  it("switches the theme without the page cross-fade", async () => {
    const started = viewTransitions();
    setPreferences({ motion: "full", theme: "light" });
    render(<ThemeButton />);
    await userEvent.click(screen.getByRole("button", { name: "Dark theme" }));
    expect(started).toHaveBeenCalledOnce();

    setPreferences({ motion: "reduced" });
    await userEvent.click(screen.getByRole("button", { name: "Light theme" }));
    expect(started).toHaveBeenCalledOnce();
    expect(document.documentElement).not.toHaveClass("dark");
    expect(document.documentElement).toHaveAttribute("data-reduce-motion", "");
  });

  it("still opens and closes dialogs and menus at once", async () => {
    setPreferences({ motion: "reduced" });
    render(<Confirm />);
    await userEvent.click(screen.getByRole("button", { name: "Revoke…" }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});

describe("Badge", () => {
  it("shows a status in its tone, and a count as a number pill", () => {
    render(
      <>
        <Badge tone="destructive">failed</Badge>
        <Badge count>12</Badge>
      </>,
    );
    expect(screen.getByText("failed")).toHaveAttribute("data-tone", "destructive");
    expect(screen.getByText("12")).toHaveAttribute("data-tone", "neutral");
  });

  it("gives each job state its tone, and an unknown one the neutral look", () => {
    render(
      <>
        <StateBadge state="succeeded" label="Succeeded" />
        <StateBadge state="running" label="Running" />
        <StateBadge state="exploded" label="exploded" />
      </>,
    );
    expect(screen.getByText("Succeeded")).toHaveAttribute("data-tone", "positive");
    expect(screen.getByText("Running")).toHaveAttribute("data-tone", "route");
    expect(screen.getByText("exploded")).toHaveAttribute("data-tone", "neutral");
  });
});

describe("Avatar", () => {
  it("shows two initials of a username", () => {
    expect(initials("alice.smith")).toBe("AS");
    expect(initials("bob")).toBe("BO");
    expect(initials("jan-kowalski@sso")).toBe("JK");
    expect(initials("Zoë Weiß")).toBe("ZW");
    expect(initials("")).toBe("?");
  });

  it("is decoration: the name beside it is what assistive technology reads", () => {
    render(
      <p>
        <Avatar name="alice.smith" /> alice.smith
      </p>,
    );
    expect(screen.getByText("AS").closest("[aria-hidden='true']")).not.toBeNull();
  });
});

function Period() {
  const [value, setValue] = useState("week");
  return (
    <ToggleGroup
      type="single"
      aria-label="Period"
      value={value}
      onValueChange={(v) => v && setValue(v)}
    >
      <ToggleGroupItem value="day">Day</ToggleGroupItem>
      <ToggleGroupItem value="week">Week</ToggleGroupItem>
      <ToggleGroupItem value="month">Month</ToggleGroupItem>
    </ToggleGroup>
  );
}

describe("ToggleGroup", () => {
  it("picks one choice, by pointer or by keyboard", async () => {
    render(<Period />);
    const group = screen.getByRole("radiogroup", { name: "Period" });
    expect(within(group).getByRole("radio", { name: "Week" })).toBeChecked();

    await userEvent.click(within(group).getByRole("radio", { name: "Day" }));
    expect(within(group).getByRole("radio", { name: "Day" })).toBeChecked();
    expect(within(group).getByRole("radio", { name: "Week" })).not.toBeChecked();

    // Arrow keys move between the choices (one tab stop), Space picks.
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    expect(within(group).getByRole("radio", { name: "Month" })).toHaveFocus();
    await userEvent.keyboard(" ");
    expect(within(group).getByRole("radio", { name: "Month" })).toBeChecked();
  });

  it("keeps a choice when the picked one is pressed again", async () => {
    render(<Period />);
    await userEvent.click(screen.getByRole("radio", { name: "Week" }));
    expect(screen.getByRole("radio", { name: "Week" })).toBeChecked();
  });
});

describe("Breadcrumb", () => {
  it("leads back by links and marks where you are", () => {
    render(
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="/">Libraries</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Settings</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>,
    );
    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(nav).getByRole("link", { name: "Libraries" })).toHaveAttribute("href", "/");
    expect(within(nav).getByText("Settings")).toHaveAttribute("aria-current", "page");
    // The separators are drawn, not read.
    expect(within(nav).getAllByRole("listitem")).toHaveLength(2);
  });

  it("is named in Polish", () => {
    setPreferences({ language: "pl" });
    render(
      <Breadcrumb>
        <BreadcrumbList />
      </Breadcrumb>,
    );
    expect(screen.getByRole("navigation", { name: "Ścieżka nawigacji" })).toBeInTheDocument();
    resetPreferences();
  });
});

describe("Meter", () => {
  it("says how far it got, clamped to 0–100, or that the total is not known yet", () => {
    render(
      <>
        <Meter value={40} label="Import of v1.4.0" />
        <Meter value={140} label="Budget" role="meter" />
        <Meter value={null} label="Embedding" />
      </>,
    );
    expect(screen.getByRole("progressbar", { name: "Import of v1.4.0" })).toHaveAttribute(
      "aria-valuenow",
      "40",
    );
    expect(screen.getByRole("meter", { name: "Budget" })).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByRole("progressbar", { name: "Embedding" })).not.toHaveAttribute(
      "aria-valuenow",
    );
  });
});

describe("LibraryMark", () => {
  afterEach(() => resetPreferences());

  it("shows the library's logo as decoration, and a generic mark when it does not load", () => {
    const { container } = render(<LibraryMark id="/acme/payments" logo="/logo.svg?v=1" />);
    const logo = container.querySelector("img");
    expect(logo).toHaveAttribute("src", "/logo.svg?v=1");
    expect(logo).toHaveAttribute("alt", "");
    fireEvent.error(logo as HTMLImageElement);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("falls back to the monogram when logos are turned off", () => {
    setPreferences({ library_logos: false });
    const { container } = render(<LibraryMark id="/acme/payments" logo="/logo.svg?v=1" />);
    expect(container.querySelector("img")).toBeNull();
    expect(container).toHaveTextContent("PA");
  });
});
