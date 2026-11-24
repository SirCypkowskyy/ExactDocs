import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
  useSearch,
} from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ArrowRight, Trash2 } from "lucide-react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { TestRouter } from "@/shared/lib/test-router";
import { ConfirmDialog } from "../confirm-dialog";
import { TooltipProvider } from "../tooltip";
import { LibraryCell } from "./cells";
import { DataTable } from "./data-table";
import { DataTablePagination } from "./pagination";
import type { RowAction } from "./row-actions";
import { restoreRowFocus } from "./row-actions";
import type { ServerSource } from "./server-pages";
import { DataTableSkeleton } from "./states";
import { parseFacet, parseTableSearch, stringifySearch, type TableConfig } from "./table-search";
import { DataTableToolbar } from "./toolbar";
import {
  type ClientQuery,
  type TableFilter,
  useDataTable,
  useLocalDataTable,
} from "./use-data-table";

const STATES = ["queued", "running", "failed"] as const;

interface Thing {
  id: string;
  name: string;
  state: (typeof STATES)[number];
}

/** 23 things: "Thing 01" to "Thing 23", queued, running and failed in turn (8, 8 and 7). */
const THINGS: Thing[] = Array.from({ length: 23 }, (_, i) => ({
  id: `t${i + 1}`,
  name: `Thing ${String(i + 1).padStart(2, "0")}`,
  state: STATES[i % 3] ?? "queued",
}));

const CLIENT: TableConfig = { id: "things", sortFields: ["name"], maxRows: 50 };
const SERVER: TableConfig = { id: "remote", sortFields: [] };

const columns: ColumnDef<Thing>[] = [
  { accessorKey: "name", header: "Name", meta: { priority: 1 } },
  { accessorKey: "state", header: "State", enableSorting: false, meta: { priority: 2 } },
];

const filters: TableFilter[] = [
  { id: "state", title: "State", options: STATES.map((s) => ({ value: s, label: s })) },
];

const picked: Thing[] = [];
const actions = (thing: Thing): RowAction<Thing>[] => [
  { id: "open", label: "Open thing", icon: ArrowRight, onSelect: (t) => picked.push(t) },
  {
    id: "remove",
    label: "Remove thing",
    icon: Trash2,
    destructive: true,
    group: true,
    onSelect: (t) => picked.push({ ...t, name: `removed ${thing.name}` }),
  },
];

function ClientThings({ query }: { query: ClientQuery<Thing> }) {
  const raw = useSearch({ strict: false }) as Record<string, unknown>;
  const search = { ...parseTableSearch(raw, CLIENT), state: parseFacet(raw.state, STATES) };
  const model = useDataTable({
    config: CLIENT,
    search,
    columns,
    getRowId: (t) => t.id,
    filters,
    query,
  });
  return (
    <>
      <DataTableToolbar model={model} search={{ label: "Find things" }} columns={false} />
      <DataTable
        model={model}
        label="Things"
        rowActions={actions}
        rowLabel={(t) => t.name}
        empty={{ title: "No things yet", body: "Add one to see it here." }}
      />
      <DataTablePagination model={model} />
    </>
  );
}

function ServerThings({ source }: { source: ServerSource<Thing> }) {
  const raw = useSearch({ strict: false }) as Record<string, unknown>;
  const model = useDataTable({
    config: SERVER,
    search: parseTableSearch(raw, SERVER),
    columns,
    getRowId: (t) => t.id,
    source,
  });
  return (
    <>
      <DataTable model={model} label="Things" />
      <DataTablePagination model={model} />
    </>
  );
}

/** A list API over `count` things that pages by offset (G8) and records each request. */
function offsetSource(count: number) {
  const asked: { limit: number; offset: number | undefined }[] = [];
  const source: ServerSource<Thing> = {
    key: ["remote things", count],
    paging: "offset",
    fetchPage: async ({ limit, offset }) => {
      asked.push({ limit, offset });
      const start = offset ?? 0;
      const rows = Array.from({ length: Math.max(0, Math.min(limit, count - start)) }, (_, i) => ({
        id: `r${start + i + 1}`,
        name: `Remote ${start + i + 1}`,
        state: "queued" as const,
      }));
      return { rows, total: count, nextCursor: null };
    },
  };
  return { source, asked };
}

const ready = (data: Thing[], over: Partial<ClientQuery<Thing>> = {}): ClientQuery<Thing> => ({
  data,
  isPending: false,
  isError: false,
  refetch: () => {},
  ...over,
});

function renderAt(start: string, page: () => React.ReactNode) {
  const history = createMemoryHistory({ initialEntries: [start] });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <TestRouter history={history} pages={{ "/things": page }} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return history;
}

const params = (history: ReturnType<typeof createMemoryHistory>) =>
  new URLSearchParams(history.location.search);

const rowNames = () =>
  within(screen.getByRole("table", { name: "Things" }))
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getByRole("rowheader").textContent);

beforeEach(() => {
  localStorage.clear();
  picked.length = 0;
});
afterEach(() => {
  resetPreferences();
  vi.unstubAllGlobals();
});

describe("DataTable v2 in client mode", () => {
  it("pages a bounded list in the browser, with Last and no size above its cap", async () => {
    const history = renderAt("/things", () => <ClientThings query={ready(THINGS)} />);

    expect(await screen.findByText("1–20 of 23")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Things" })).toHaveAttribute("aria-rowcount", "24");
    const sizes = within(screen.getByLabelText("Rows per page")).getAllByRole("option");
    expect(sizes.map((o) => o.textContent)).toEqual(["5", "20", "50"]);

    await userEvent.click(screen.getByRole("button", { name: "Last page" }));

    expect(await screen.findByText("21–23 of 23")).toBeInTheDocument();
    expect(rowNames()).toEqual(["Thing 21", "Thing 22", "Thing 23"]);
    expect(params(history).get("page")).toBe("2");
    expect(screen.getByRole("button", { name: "Last page" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("sorts in the browser, keeps the sort in the URL and goes back to page 1", async () => {
    const history = renderAt("/things?page=2", () => <ClientThings query={ready(THINGS)} />);
    await screen.findByText("21–23 of 23");

    await userEvent.click(screen.getByRole("button", { name: "Sort by Name" }));
    expect(await screen.findByText("1–20 of 23")).toBeInTheDocument();
    expect(rowNames()[0]).toBe("Thing 01");
    expect(params(history).get("sort")).toBe("name");
    expect(params(history).get("page")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Sort by Name, sorted ascending" }));
    await waitFor(() => expect(rowNames()[0]).toBe("Thing 23"));
    expect(params(history).get("sort")).toBe("-name");
    expect(screen.getByRole("columnheader", { name: /Name/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });

  it("counts each facet value and filters by any of the picked ones", async () => {
    const history = renderAt("/things", () => <ClientThings query={ready(THINGS)} />);
    await screen.findByText("1–20 of 23");

    await userEvent.click(screen.getByRole("button", { name: "State" }));
    const failed = await screen.findByRole("option", { name: /failed/ });
    expect(failed).toHaveTextContent("7");
    expect(screen.getByRole("option", { name: /queued/ })).toHaveTextContent("8");
    await userEvent.click(failed);
    await userEvent.click(screen.getByRole("option", { name: /queued/ }));
    await userEvent.keyboard("{Escape}");

    expect(await screen.findByText("1–15 of 15")).toBeInTheDocument();
    // Written in the options' order, whatever the order of the clicks.
    expect(params(history).get("state")).toBe("queued,failed");
    expect(screen.getByRole("button", { name: "State, 2 selected" })).toBeInTheDocument();
  });

  it("filters by the text in the search box once typing pauses", async () => {
    const history = renderAt("/things", () => <ClientThings query={ready(THINGS)} />);
    await screen.findByText("1–20 of 23");

    await userEvent.type(screen.getByLabelText("Find things"), "Thing 1");

    expect(await screen.findByText("1–10 of 10")).toBeInTheDocument();
    expect(params(history).get("q")).toBe("Thing 1");
  });

  it("reads the whole view from a link and writes it back in the same form", async () => {
    const history = renderAt(
      "/things?q=Thing%201&state=failed,queued&sort=-name&page=2&size=5",
      () => <ClientThings query={ready(THINGS)} />,
    );

    // Things 10 to 19 that are queued or failed, newest name first, second page of five.
    expect(await screen.findByText("6–7 of 7")).toBeInTheDocument();
    expect(rowNames()).toEqual(["Thing 12", "Thing 10"]);
    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Find things")).toHaveValue("Thing 1");
    expect(screen.getByLabelText("Rows per page")).toHaveValue("5");
    const chips = screen.getByRole("list", { name: "Active filters" });
    expect(
      within(chips)
        .getAllByRole("listitem")
        .map((c) => c.textContent),
    ).toEqual(["State: queued", "State: failed"]);

    await userEvent.click(
      within(chips).getByRole("button", { name: "Remove filter State: failed" }),
    );

    // A new filter goes back to page 1 and keeps everything else.
    expect(await screen.findByText("1–4 of 4")).toBeInTheDocument();
    expect(Object.fromEntries(params(history))).toEqual({
      q: "Thing 1",
      state: "queued",
      sort: "-name",
      size: "5",
    });

    await userEvent.click(screen.getByRole("button", { name: "Clear all" }));

    expect(await screen.findByText("1–5 of 23")).toBeInTheDocument();
    expect(Object.fromEntries(params(history))).toEqual({ sort: "-name", size: "5" });
    expect(screen.getByLabelText("Find things")).toHaveValue("");
  });

  it("shows the last page instead of one past the end", async () => {
    const history = renderAt("/things?page=9", () => <ClientThings query={ready(THINGS)} />);
    expect(await screen.findByText("21–23 of 23")).toBeInTheDocument();
    expect(params(history).get("page")).toBe("2");
  });

  it("remembers the chosen size in this browser, the URL still winning", async () => {
    const history = renderAt("/things", () => <ClientThings query={ready(THINGS)} />);
    await screen.findByText("1–20 of 23");

    await userEvent.selectOptions(screen.getByLabelText("Rows per page"), "5");

    expect(await screen.findByText("1–5 of 23")).toBeInTheDocument();
    expect(params(history).get("size")).toBe("5");
    expect(JSON.parse(localStorage.getItem("exactdocs-table-sizes") ?? "{}")).toEqual({
      things: 5,
    });
  });
});

describe("LibraryCell", () => {
  it("links the title, with the ID and one line of description under it", async () => {
    renderAt("/things", () => (
      <LibraryCell id="/acme/payments" title="Acme Payments" description="Charge cards." />
    ));
    const link = await screen.findByRole("link", { name: "Acme Payments" });
    expect(link).toHaveAttribute("href", "/libraries/acme/payments");
    expect(screen.getByText("/acme/payments")).toHaveClass("font-mono");
    expect(screen.getByText("Charge cards.")).toHaveClass("max-lg:hidden", "truncate");
  });

  it("links the mono ID alone when there is nothing else", async () => {
    renderAt("/things", () => <LibraryCell id="/acme/payments" />);
    const link = await screen.findByRole("link", { name: "/acme/payments" });
    expect(within(link).getByText("/acme/payments")).toHaveClass("font-mono");
  });
});

describe("DataTableSkeleton", () => {
  it("holds a route's final layout: headers, rows in each column's shape, hidden from readers", () => {
    const { container } = render(
      <DataTableSkeleton
        filters={2}
        rows={5}
        columns={[
          { id: "name", header: "Name", shape: "avatar" },
          { id: "size", header: "Size", shape: "number", className: "max-lg:hidden" },
        ]}
      />,
    );
    const frame = container.querySelector("[data-slot=data-table-skeleton]") as HTMLElement;
    expect(frame).toHaveAttribute("aria-hidden", "true");
    const heads = [...frame.querySelectorAll("thead th")];
    expect(heads.map((h) => h.textContent)).toEqual(["Name", "Size", ""]);
    expect(heads[1]).toHaveClass("max-lg:hidden");
    const rows = frame.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(5);
    expect(rows[0]?.querySelectorAll("td")[1]).toHaveClass("max-lg:hidden");
  });
});

describe("DataTable v2's row headers", () => {
  it("makes the title column's cell the row's header, the others plain cells", async () => {
    renderAt("/things", () => <ClientThings query={ready(THINGS)} />);
    await screen.findByText("1–20 of 23");
    const row = screen.getByRole("rowheader", { name: "Thing 01" }).closest("tr") as HTMLElement;
    expect(within(row).getByRole("rowheader")).toHaveAttribute("scope", "row");
    expect(
      within(row)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["queued", ""]);
  });
});

describe("DataTable v2's states", () => {
  it("says what the list is for when it is empty, and how to get back when nothing matches", async () => {
    renderAt("/things", () => <ClientThings query={ready([])} />);
    expect(await screen.findByText("No things yet")).toBeInTheDocument();
    expect(screen.getByText("Add one to see it here.")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Pagination" })).not.toBeInTheDocument();
  });

  it("offers Clear filters when the filters match nothing", async () => {
    const history = renderAt("/things?q=nothing%20like%20this", () => (
      <ClientThings query={ready(THINGS)} />
    ));
    expect(await screen.findByText("Nothing matches")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(await screen.findByText("1–20 of 23")).toBeInTheDocument();
    expect(history.location.search).toBe("");
  });

  it("says the list failed inside its frame and retries", async () => {
    const refetch = vi.fn();
    renderAt("/things", () => (
      <ClientThings query={ready([], { data: undefined, isError: true, refetch })} />
    ));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load this list.");

    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(refetch).toHaveBeenCalledOnce();
  });

  it("names its retry after what it retries when the page asks", async () => {
    const refetch = vi.fn();
    renderAt("/things", () => {
      const model = useDataTable({
        config: CLIENT,
        search: {},
        columns,
        getRowId: (t: Thing) => t.id,
        query: ready([], { data: undefined, isError: true, refetch }),
      });
      return <DataTable model={model} label="Things" retryLabel="Retry the list" />;
    });
    const alert = await screen.findByRole("alert");
    await userEvent.click(within(alert).getByRole("button", { name: "Retry the list" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("holds the final layout with placeholder rows while loading", async () => {
    renderAt("/things", () => (
      <ClientThings query={ready([], { data: undefined, isPending: true })} />
    ));
    const table = await screen.findByRole("table", { name: "Things" });
    expect(table).toHaveAttribute("aria-busy", "true");
    // One placeholder row per row of the page, hidden from assistive technology.
    expect(table.querySelectorAll("tbody tr[aria-hidden='true']")).toHaveLength(20);
  });
});

describe("DataTable v2's row actions", () => {
  it("offers the same actions in the row's menu and in its context menu", async () => {
    renderAt("/things", () => <ClientThings query={ready(THINGS)} />);
    await screen.findByText("1–20 of 23");

    await userEvent.click(screen.getByRole("button", { name: "More actions for Thing 02" }));
    const menu = await screen.findByRole("menu");
    const visible = within(menu)
      .getAllByRole("menuitem")
      .map((i) => i.textContent);
    expect(visible).toEqual(["Open thing", "Remove thing"]);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());

    const row = screen.getByRole("rowheader", { name: "Thing 02" }).closest("tr") as HTMLElement;
    fireEvent.contextMenu(row);

    const context = await screen.findByRole("menu");
    expect(
      within(context)
        .getAllByRole("menuitem")
        .map((i) => i.textContent),
    ).toEqual(visible);
    await userEvent.click(within(context).getByRole("menuitem", { name: "Open thing" }));
    expect(picked.map((t) => t.id)).toEqual(["t2"]);
  });
});

/** Things whose Remove asks first, focus going back to the row's kebab on Cancel. */
function ConfirmingThings() {
  const raw = useSearch({ strict: false }) as Record<string, unknown>;
  const model = useDataTable({
    config: CLIENT,
    search: parseTableSearch(raw, CLIENT),
    columns,
    getRowId: (t) => t.id,
    query: ready(THINGS),
  });
  const [removing, setRemoving] = useState<Thing>();
  return (
    <>
      <h1 tabIndex={-1}>Things</h1>
      <DataTable
        model={model}
        label="Things"
        rowLabel={(t) => t.name}
        rowActions={() => [
          { id: "remove", label: "Remove thing", icon: Trash2, onSelect: setRemoving },
        ]}
      />
      <ConfirmDialog
        open={removing !== undefined}
        onOpenChange={(open) => {
          if (!open) setRemoving(undefined);
        }}
        title={`Remove ${removing?.name ?? ""}?`}
        confirmLabel="Remove"
        onConfirm={() => setRemoving(undefined)}
        onCloseAutoFocus={restoreRowFocus}
      />
    </>
  );
}

/** Things on a page whose `q` is its own: the table's search box writes `filter`. */
function FilteredThings() {
  const raw = useSearch({ strict: false }) as Record<string, unknown>;
  const search = { ...parseTableSearch({ ...raw, q: raw.filter }, CLIENT) };
  const model = useDataTable({
    config: CLIENT,
    search,
    qParam: "filter",
    columns,
    getRowId: (t) => t.id,
    query: ready(THINGS),
  });
  return (
    <>
      <DataTableToolbar model={model} search={{ label: "Find things" }} columns={false} />
      <DataTable model={model} label="Things" />
      <DataTablePagination model={model} />
    </>
  );
}

/** A table inside another page: its view lives in the component, not in the URL. */
function EmbeddedThings() {
  const model = useLocalDataTable({
    config: CLIENT,
    rows: THINGS,
    columns,
    getRowId: (t) => t.id,
    filters,
  });
  return (
    <>
      <DataTableToolbar model={model} search={{ label: "Find things" }} columns={false} />
      <DataTable model={model} label="Things" />
      <DataTablePagination model={model} />
    </>
  );
}

/** A list that failed: the page explains the failure the model hands it. */
function FailingThings({ query }: { query?: ClientQuery<Thing> }) {
  const raw = useSearch({ strict: false }) as Record<string, unknown>;
  const search = parseTableSearch(raw, query ? CLIENT : SERVER);
  const options = { search, columns, getRowId: (t: Thing) => t.id };
  const model = useDataTable(
    query
      ? { ...options, config: CLIENT, query }
      : {
          ...options,
          config: SERVER,
          source: {
            key: ["refused things"],
            fetchPage: () => Promise.reject(new Error("You can't list these.")),
          },
        },
  );
  return (
    <DataTable
      model={model}
      label="Things"
      errorMessage={model.error instanceof Error ? model.error.message : "Unknown"}
    />
  );
}

describe("DataTable v2's view options", () => {
  it("keeps the URL's hash when it writes the view", async () => {
    const history = renderAt("/things#versions", () => <ClientThings query={ready(THINGS)} />);
    await screen.findByText("1–20 of 23");

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(await screen.findByText("21–23 of 23")).toBeInTheDocument();
    expect(history.location.hash).toBe("#versions");
    expect(params(history).get("page")).toBe("2");
  });

  it("writes its search box to another URL key when the page owns `q`", async () => {
    const history = renderAt("/things?q=page%20search&filter=Thing%202", () => <FilteredThings />);
    expect(await screen.findByText("1–4 of 4")).toBeInTheDocument();
    expect(screen.getByLabelText("Find things")).toHaveValue("Thing 2");

    await userEvent.clear(screen.getByLabelText("Find things"));
    await userEvent.type(screen.getByLabelText("Find things"), "nothing like this");
    expect(await screen.findByText("Nothing matches")).toBeInTheDocument();
    expect(params(history).get("filter")).toBe("nothing like this");
    expect(params(history).get("q")).toBe("page search");

    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(await screen.findByText("1–20 of 23")).toBeInTheDocument();
    expect(Object.fromEntries(params(history))).toEqual({ q: "page search" });
  });

  it("keeps an embedded table's view out of the page's URL", async () => {
    const history = renderAt("/things?q=page%20search", () => <EmbeddedThings />);
    expect(await screen.findByText("1–20 of 23")).toBeInTheDocument();
    expect(screen.getByLabelText("Find things")).toHaveValue("");

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("21–23 of 23")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "State" }));
    await userEvent.click(await screen.findByRole("option", { name: /failed/ }));
    await userEvent.keyboard("{Escape}");

    expect(await screen.findByText("1–7 of 7")).toBeInTheDocument();
    expect(history.location.search).toBe("?q=page%20search");
  });

  it("hands the page why a client list failed", async () => {
    renderAt("/things", () => (
      <FailingThings
        query={ready([], { data: undefined, isError: true, error: new Error("Sign in again.") })}
      />
    ));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sign in again.");
  });

  it("hands the page why a server page failed", async () => {
    renderAt("/things", () => <FailingThings />);
    expect(await screen.findByRole("alert")).toHaveTextContent("You can't list these.");
  });
});

describe("DataTable v2's row actions and focus", () => {
  it("gives focus back to the row's kebab after a dialog its mouse-opened menu asked for", async () => {
    const user = userEvent.setup();
    renderAt("/things", () => <ConfirmingThings />);
    const kebab = await screen.findByRole("button", { name: "More actions for Thing 03" });
    // Something else had focus before (the page's heading after navigation).
    screen.getByRole("heading", { name: "Things" }).focus();

    await user.pointer({ keys: "[MouseLeft]", target: kebab });
    await user.click(await screen.findByRole("menuitem", { name: "Remove thing" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Remove Thing 03?" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    await waitFor(() => expect(kebab).toHaveFocus());
  });
});

describe("DataTable v2 on a phone", () => {
  it("turns each row into a card: its title, its meta cells named, its menu", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: query === "(max-width: 47.99rem)",
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      })),
    );
    renderAt("/things?size=5", () => <ClientThings query={ready(THINGS)} />);

    const cards = await screen.findByRole("list", { name: "Things" });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const first = within(cards).getAllByRole("listitem")[0] as HTMLElement;
    expect(first).toHaveTextContent("Thing 01");
    expect(first).toHaveTextContent("State: queued");
    expect(
      within(first).getByRole("button", { name: "More actions for Thing 01" }),
    ).toBeInTheDocument();
  });
});

describe("DataTable v2 over an offset API", () => {
  it("offers Last and reaches it in one request", async () => {
    const { source, asked } = offsetSource(95);
    const history = renderAt("/things", () => <ServerThings source={source} />);
    expect(await screen.findByText("1–20 of 95")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Last page" }));

    expect(await screen.findByText("81–95 of 95")).toBeInTheDocument();
    // One page per request, from its offset: no walk from the start.
    expect(asked).toContainEqual({ limit: 20, offset: 80 });
    expect(asked.every((a) => a.limit === 20)).toBe(true);
    expect(params(history).get("page")).toBe("5");
    expect(screen.getByText("Page 5 of 5", { selector: "[role=status]" })).toBeInTheDocument();
  });
});

describe("DataTable v2 in Polish", () => {
  it("names the pagination and formats its figures the Polish way", async () => {
    setPreferences({ language: "pl" });
    const { source } = offsetSource(12_345);
    renderAt("/things", () => <ServerThings source={source} />);

    const nav = await screen.findByRole("navigation", { name: "Stronicowanie" });
    expect(await within(nav).findByText(/^1–20 z 12\s345$/)).toBeInTheDocument();
    expect(within(nav).getByText("Strona 1 z 618")).toBeInTheDocument();
    expect(within(nav).getByLabelText("Wierszy na stronie")).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: "Pierwsza strona" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(within(nav).getByRole("button", { name: "Ostatnia strona" })).toBeInTheDocument();

    await userEvent.click(within(nav).getByRole("button", { name: "Następna strona" }));

    expect(await within(nav).findByText(/^21–40 z 12\s345$/)).toBeInTheDocument();
    expect(
      within(nav).getByText("Strona 2 z 618", { selector: "[role=status]" }),
    ).toBeInTheDocument();
  });
});

describe("DataTable v2 behind a route that validates its search", () => {
  it("keeps facets in the URL as `a,b` after the route turns them into lists", async () => {
    const history = createMemoryHistory({ initialEntries: ["/things?state=failed"] });
    const root = createRootRoute({ component: Outlet });
    const things = createRoute({
      getParentRoute: () => root,
      path: "/things",
      validateSearch: (raw: Record<string, unknown>) => ({
        ...parseTableSearch(raw, CLIENT),
        state: parseFacet(raw.state, STATES),
      }),
      component: () => <ClientThings query={ready(THINGS)} />,
    });
    const router = createRouter({
      routeTree: root.addChildren([things]),
      history,
      stringifySearch,
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <TooltipProvider>
          <RouterProvider router={router as never} />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("1–7 of 7")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "State, 1 selected" }));
    await userEvent.click(await screen.findByRole("option", { name: /queued/ }));
    await userEvent.keyboard("{Escape}");

    expect(await screen.findByText("1–15 of 15")).toBeInTheDocument();
    expect(history.location.search).toBe("?state=queued%2Cfailed");
  });
});
