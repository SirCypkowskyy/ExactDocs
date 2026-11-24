import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import {
  type LibraryChoices,
  LibraryCombobox,
  type LibraryOption,
  recentLibraries,
} from "./library-combobox";

const LIBS: LibraryOption[] = [
  { id: "/acme/payments", title: "Payments SDK", logo: null },
  { id: "/acme/web", title: "web", logo: null },
  { id: "/fixture/docs-repo", title: "Docs", logo: null },
];

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function Single({
  options = LIBS,
  query,
  custom,
  initial,
  onChange = () => {},
}: {
  options?: LibraryOption[] | undefined;
  query?: (text: string) => {
    queryKey: readonly unknown[];
    queryFn: () => Promise<LibraryChoices>;
  };
  custom?: (text: string) => boolean;
  initial?: string;
  onChange?: (id: string | undefined) => void;
}) {
  const [value, setValue] = useState<string | undefined>(initial);
  return (
    <LibraryCombobox
      label="Library"
      variant="filter"
      value={value}
      {...(query ? { query } : { options })}
      {...(custom && { custom })}
      onChange={(id) => {
        setValue(id);
        onChange(id);
      }}
    />
  );
}

function Multiple({ onChange = () => {} }: { onChange?: (ids: string[]) => void }) {
  const [value, setValue] = useState<string[]>([]);
  return (
    <LibraryCombobox
      multiple
      label="Libraries"
      placeholder="All libraries"
      options={LIBS}
      value={value}
      onChange={(ids) => {
        setValue(ids);
        onChange(ids);
      }}
    />
  );
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  localStorage.clear();
  resetPreferences();
});

describe("LibraryCombobox", () => {
  it("is a combobox with a listbox of options, named and announced", async () => {
    wrap(<Single />);
    const trigger = screen.getByRole("button", { name: "Library" });
    await userEvent.click(trigger);
    const input = screen.getByRole("combobox", { name: "Find a library" });
    expect(input).toHaveFocus();
    expect(input).toHaveAttribute("aria-expanded", "true");
    const listbox = screen.getByRole("listbox", { name: "Library" });
    expect(input).toHaveAttribute("aria-controls", listbox.id);
    expect(within(listbox).getAllByRole("option")).toHaveLength(3);
    expect(screen.getByRole("status")).toHaveTextContent("3 libraries");
    // The highlighted option is the input's active descendant.
    const first = within(listbox).getAllByRole("option")[0];
    expect(input).toHaveAttribute("aria-activedescendant", first?.id);
  });

  it("works by keyboard: arrows, End, Home, Enter picks, focus returns to the trigger", async () => {
    const onChange = vi.fn();
    wrap(<Single onChange={onChange} />);
    const trigger = screen.getByRole("button", { name: "Library" });
    trigger.focus();
    await userEvent.keyboard("{Enter}");
    const input = screen.getByRole("combobox", { name: "Find a library" });
    const active = () => document.getElementById(input.getAttribute("aria-activedescendant") ?? "");
    expect(active()).toHaveTextContent("/acme/payments");
    await userEvent.keyboard("{ArrowDown}");
    expect(active()).toHaveTextContent("/acme/web");
    await userEvent.keyboard("{End}");
    expect(active()).toHaveTextContent("/fixture/docs-repo");
    await userEvent.keyboard("{Home}");
    expect(active()).toHaveTextContent("/acme/payments");
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("/acme/web");
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    const after = screen.getByRole("button", { name: "Library: /acme/web" });
    await waitFor(() => expect(after).toHaveFocus());
  });

  it("closes on Escape without choosing", async () => {
    const onChange = vi.fn();
    wrap(<Single onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Library" }));
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Library" })).toHaveFocus();
  });

  it("filters as you type, by ID or title, and says when nothing matches", async () => {
    wrap(<Single />);
    await userEvent.click(screen.getByRole("button", { name: "Library" }));
    await userEvent.keyboard("payments");
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
      "/acme/payments Payments SDK",
    ]);
    await userEvent.clear(screen.getByRole("combobox"));
    await userEvent.keyboard("docs");
    expect(screen.getAllByRole("option")).toHaveLength(1);
    await userEvent.keyboard("zzz");
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByRole("status")).toHaveTextContent("No library matches “docszzz”.");
  });

  it("marks the chosen library and offers Clear", async () => {
    const onChange = vi.fn();
    wrap(<Single initial="/acme/web" onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Library: /acme/web" }));
    expect(screen.getByRole("option", { name: /\/acme\/web/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await userEvent.click(screen.getByRole("option", { name: "Clear" }));
    expect(onChange).toHaveBeenCalledWith(undefined);
  });

  it("keeps the recent picks of this browser first, at most five", async () => {
    wrap(<Single />);
    const trigger = () => screen.getByRole("button", { name: /^Library/ });
    await userEvent.click(trigger());
    await userEvent.click(screen.getByRole("option", { name: /\/fixture\/docs-repo/ }));
    await userEvent.click(trigger());
    const recent = screen.getByRole("group", { name: "Recent" });
    expect(
      within(recent)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["/fixture/docs-repo Docs"]);
    expect(screen.getByRole("group", { name: "All libraries" })).toBeInTheDocument();
    // Typing searches every library; the shortcut steps aside.
    await userEvent.keyboard("acme");
    expect(screen.queryByRole("group", { name: "Recent" })).toBeNull();
    expect(recentLibraries().map((r) => r.id)).toEqual(["/fixture/docs-repo"]);

    localStorage.setItem(
      "exactdocs-recent-libraries",
      JSON.stringify(["a", "b", "c", "d", "e", "f"].map((x) => ({ id: `/o/${x}` }))),
    );
    expect(recentLibraries()).toHaveLength(5);
  });

  it("works without storage", async () => {
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const onChange = vi.fn();
    wrap(<Single onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Library" }));
    await userEvent.click(screen.getByRole("option", { name: /\/acme\/web/ }));
    expect(onChange).toHaveBeenCalledWith("/acme/web");
    get.mockRestore();
    set.mockRestore();
  });

  it("drops a recent library that is no longer offered", async () => {
    localStorage.setItem(
      "exactdocs-recent-libraries",
      JSON.stringify([{ id: "/gone/lib" }, { id: "/acme/web" }]),
    );
    wrap(<Single />);
    await userEvent.click(screen.getByRole("button", { name: "Library" }));
    const recent = screen.getByRole("group", { name: "Recent" });
    expect(
      within(recent)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["/acme/web"]);
  });

  it("groups by owner above twenty libraries", async () => {
    const many = Array.from({ length: 24 }, (_, i) => ({
      id: `/${i % 2 ? "beta" : "alpha"}/lib-${String(i).padStart(2, "0")}`,
    }));
    wrap(<Single options={many} />);
    await userEvent.click(screen.getByRole("button", { name: "Library" }));
    const alpha = screen.getByRole("group", { name: "alpha" });
    const beta = screen.getByRole("group", { name: "beta" });
    expect(within(alpha).getAllByRole("option")).toHaveLength(12);
    expect(within(beta).getAllByRole("option")).toHaveLength(12);
    expect(screen.queryByRole("group", { name: "All libraries" })).toBeNull();
  });

  it("picks several in multiple mode, shows them as removable chips", async () => {
    const onChange = vi.fn();
    wrap(<Multiple onChange={onChange} />);
    const trigger = screen.getByRole("button", { name: "Libraries All libraries" });
    await userEvent.click(trigger);
    expect(screen.getByRole("listbox")).toHaveAttribute("aria-multiselectable", "true");
    await userEvent.click(screen.getByRole("option", { name: /\/acme\/payments/ }));
    await userEvent.click(screen.getByRole("option", { name: /\/fixture\/docs-repo/ }));
    // The list stays open for more.
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith(["/acme/payments", "/fixture/docs-repo"]);
    await userEvent.keyboard("{Escape}");
    expect(
      screen.getByRole("button", { name: "Libraries 2 libraries chosen" }),
    ).toBeInTheDocument();
    const chips = screen.getByRole("list", { name: "Chosen libraries" });
    expect(within(chips).getAllByRole("listitem")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Remove /acme/payments" }));
    expect(onChange).toHaveBeenLastCalledWith(["/fixture/docs-repo"]);
  });

  it("asks the feature's query when opened, with the typed text, and retries a failure", async () => {
    let fail = true;
    const calls: string[] = [];
    const query = (text: string) => ({
      queryKey: ["test-libraries", text] as const,
      queryFn: async (): Promise<LibraryChoices> => {
        calls.push(text);
        if (fail) throw new Error("down");
        const options = LIBS.filter((l) => l.id.includes(text));
        return { options, total: text ? options.length : 40 };
      },
    });
    wrap(<Single query={query} />);
    expect(calls).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Library" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load the libraries.");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findAllByRole("option")).toHaveLength(3);
    expect(screen.getByText("Showing 3 of 40. Type to narrow the list.")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("combobox"), "fixture");
    await waitFor(() => expect(calls.at(-1)).toBe("fixture"));
    expect(screen.getAllByRole("option")).toHaveLength(1);
  });

  it("shows the loading and failed states of options the feature loads", async () => {
    const onRetry = vi.fn();
    const { rerender } = wrap(
      <LibraryCombobox
        label="Library"
        options={undefined}
        loading
        value={undefined}
        onChange={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /^Library/ }));
    expect(screen.getByRole("status")).toHaveTextContent("Loading libraries");
    expect(screen.queryByRole("listbox")).toBeNull();
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <LibraryCombobox
          label="Library"
          options={undefined}
          failed
          onRetry={onRetry}
          value={undefined}
          onChange={() => {}}
        />
      </QueryClientProvider>,
    );
    // Still open: the failure shows in place of the list.
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load the libraries.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("says when there are no libraries at all", async () => {
    wrap(<Single options={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "Library" }));
    expect(screen.getByRole("status")).toHaveTextContent("No libraries yet.");
  });

  it("offers a typed ID when the caller accepts it", async () => {
    const onChange = vi.fn();
    wrap(<Single custom={(text) => /^\/[^/]+\/[^/]+$/.test(text)} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Library" }));
    await userEvent.keyboard("/gone/lib{Enter}");
    expect(onChange).toHaveBeenCalledWith("/gone/lib");
  });

  it("speaks Polish", async () => {
    setPreferences({ language: "pl" });
    wrap(<Multiple />);
    await userEvent.click(screen.getByRole("button", { name: /Libraries/ }));
    expect(screen.getByRole("combobox", { name: "Znajdź bibliotekę" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("3 biblioteki");
    await userEvent.click(screen.getByRole("option", { name: /\/acme\/web/ }));
    await userEvent.click(screen.getByRole("option", { name: /\/acme\/payments/ }));
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: /Wybrano 2 biblioteki/ })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Wybrane biblioteki" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Usuń /acme/web" })).toBeInTheDocument();
  });
});
