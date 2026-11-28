import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LibraryBig, Plus, Search } from "lucide-react";
import { afterEach, describe, expect, it } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { Page, PageHeader } from "./page";
import { DOCS_URL, guideUrl, type HelpTopic } from "./page-help";

afterEach(() => resetPreferences());

const topic: HelpTopic = {
  title: { en: "Using the list", pl: "Jak korzystać z listy" },
  steps: [
    {
      icon: LibraryBig,
      target: "list",
      title: { en: "The list", pl: "Lista" },
      body: { en: "Every library.", pl: "Każda biblioteka." },
      guide: "getting-started/#add-your-first-library",
    },
    {
      icon: Search,
      target: "absent",
      title: { en: "Find", pl: "Szukanie" },
      body: { en: "Find one.", pl: "Znajdź jedną." },
      guide: "search/",
    },
    {
      icon: Plus,
      target: "tall",
      title: { en: "Add", pl: "Dodawanie" },
      body: { en: "Add one.", pl: "Dodaj jedną." },
      guide: "mcp/connect/",
    },
  ],
};

/** jsdom has no layout: give a target a box and record how it is scrolled. */
function placed(name: string, height: number, scrolls: unknown[]) {
  const element = document.querySelector(`[data-tour="${name}"]`) as HTMLElement;
  element.getBoundingClientRect = () =>
    ({ top: 100, left: 20, width: 300, height, bottom: 100 + height, right: 320 }) as DOMRect;
  element.scrollIntoView = (options) => void scrolls.push([name, options]);
}

function renderPage() {
  const scrolls: unknown[] = [];
  render(
    <Page>
      <PageHeader title="Libraries" help={topic} />
      <div data-tour="list">rows</div>
      <div data-tour="tall">a long table</div>
    </Page>,
  );
  placed("list", 120, scrolls);
  placed("tall", window.innerHeight * 2, scrolls);
  return { scrolls, trigger: screen.getByRole("button", { name: "Help" }) };
}

const spotlight = () => document.querySelector('[data-slot="tour-spotlight"]');

describe("PageHelp", () => {
  it("opens a tour from the header, steps with buttons and arrows, and finishes on the Help button", async () => {
    const user = userEvent.setup();
    const { trigger } = renderPage();
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Using the list" });
    const next = within(dialog).getByRole("button", { name: "Next" });
    await waitFor(() => expect(next).toHaveFocus());
    // The visible count and the announced one.
    expect(within(dialog).getAllByText(/1 of 3/)).toHaveLength(2);
    expect(dialog.querySelector("[aria-live=polite]")).toHaveTextContent("The listEvery library.");
    expect(within(dialog).getByRole("button", { name: "Back" })).toBeDisabled();
    expect(
      within(dialog).getByRole("link", { name: /Read about this in the guide/ }),
    ).toHaveAttribute("href", `${DOCS_URL}getting-started/#add-your-first-library`);

    await user.keyboard("{ArrowRight}");
    expect(within(dialog).getByText("Find")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: /guide/ })).toHaveAttribute(
      "href",
      guideUrl("search/"),
    );
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(within(dialog).getByText("The list")).toBeInTheDocument();

    await user.keyboard("{Enter}{Enter}");
    expect(within(dialog).getAllByText(/3 of 3/)).toHaveLength(2);
    expect(next).toHaveAccessibleName("Got it");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(trigger).toHaveFocus();
  });

  it("keeps Tab inside the card, and Escape closes it back to the Help button", async () => {
    const user = userEvent.setup();
    const { trigger } = renderPage();
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog");
    await user.keyboard("{ArrowRight}");
    for (let i = 0; i < 6; i += 1) {
      await user.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(trigger).toHaveFocus();
  });

  it("rings a target that is on the page, scrolls it into view, and rings nothing when it is missing", async () => {
    const user = userEvent.setup();
    const { trigger, scrolls } = renderPage();
    await user.click(trigger);
    await screen.findByRole("dialog");
    await waitFor(() => expect(spotlight()).not.toBeNull());
    await user.keyboard("{ArrowRight}");
    await waitFor(() => expect(spotlight()).toBeNull());
    await user.keyboard("{ArrowRight}");
    await waitFor(() => expect(spotlight()).not.toBeNull());
    // A target taller than the screen starts at the top; one that fits moves the least.
    expect(scrolls).toEqual([
      ["list", { block: "nearest" }],
      ["tall", { block: "start" }],
    ]);
  });

  it("speaks Polish when the interface does", async () => {
    act(() => setPreferences({ language: "pl" }));
    const user = userEvent.setup();
    render(<PageHeader title="Biblioteki" help={topic} />);
    await user.click(screen.getByRole("button", { name: "Pomoc" }));
    const dialog = await screen.findByRole("dialog", { name: "Jak korzystać z listy" });
    expect(within(dialog).getByRole("button", { name: "Dalej" })).toBeInTheDocument();
    expect(within(dialog).getAllByText(/1 z 3/)).toHaveLength(2);
  });
});
