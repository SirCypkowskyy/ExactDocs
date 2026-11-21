import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { type ArticleSummary, buildRows } from "../model/browse";
import { FileTree } from "./file-tree";

const article = (path: string): ArticleSummary => ({ path, title: "", tags: [], size: 10 });

const ARTICLES = [
  "README.md",
  "docs/api/client.md",
  "docs/guide/install.md",
  "docs/guide/resilience.md",
  "examples/basic.md",
].map(article);

/** What the tree under test shows: the pages of the router render components, so it is read here. */
let shown: { rows: ReturnType<typeof buildRows>; onToggle: (f: string, open?: boolean) => void };

function TreeUnderTest() {
  return (
    <FileTree
      owner="fixture"
      repo="docs-repo"
      version="v1.4.0"
      tags={undefined}
      selected={undefined}
      rows={shown.rows}
      scopeState={() => "idle"}
      label="Files"
      onToggle={shown.onToggle}
      onMore={vi.fn()}
      onOpen={vi.fn()}
    />
  );
}

function renderTree(expanded: string[], onToggle = vi.fn()) {
  shown = { rows: buildRows(ARTICLES, new Set(expanded)), onToggle };
  render(<TestRouter pages={{ "/": TreeUnderTest }} />);
  return onToggle;
}

describe("file tree keyboard", () => {
  it("moves between rows with the arrow keys, Home and End", async () => {
    const user = userEvent.setup();
    renderTree([]);
    const first = await screen.findByRole("treeitem", { name: "docs" });
    first.focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("treeitem", { name: "examples" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("treeitem", { name: /README/ })).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("treeitem", { name: "examples" })).toHaveFocus();
    await user.keyboard("{Home}");
    expect(first).toHaveFocus();
  });

  it("opens a closed folder with ArrowRight and closes an open one with ArrowLeft", async () => {
    const user = userEvent.setup();
    const onToggle = renderTree(["docs"]);
    const docs = await screen.findByRole("treeitem", { name: "docs" });
    docs.focus();
    await user.keyboard("{ArrowLeft}");
    expect(onToggle).toHaveBeenCalledWith("docs", false);
    const examples = screen.getByRole("treeitem", { name: "examples" });
    examples.focus();
    await user.keyboard("{ArrowRight}");
    expect(onToggle).toHaveBeenCalledWith("examples", true);
  });

  it("goes to the parent folder with ArrowLeft from a closed child", async () => {
    const user = userEvent.setup();
    renderTree(["docs"]);
    const api = await screen.findByRole("treeitem", { name: "api" });
    api.focus();
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("treeitem", { name: "docs" })).toHaveFocus();
  });

  it("jumps to the next name that starts with the typed letter", async () => {
    const user = userEvent.setup();
    renderTree([]);
    const docs = await screen.findByRole("treeitem", { name: "docs" });
    docs.focus();
    await user.keyboard("e");
    expect(screen.getByRole("treeitem", { name: "examples" })).toHaveFocus();
  });

  it("keeps one tab stop, so Tab enters and leaves the tree in one step", async () => {
    renderTree([]);
    const items = await screen.findAllByRole("treeitem");
    expect(items.filter((i) => i.getAttribute("tabindex") === "0")).toHaveLength(1);
  });
});

describe("file tree at the size of a large library", () => {
  // The API pages at 100 articles, so a reader who pages through a 7,000-article library gets
  // this many rows. The budget is generous (CI machines vary); it catches a quadratic rebuild.
  const MANY = Array.from({ length: 7000 }, (_, i) =>
    article(`docs/section-${i % 70}/page-${String(i).padStart(4, "0")}.md`),
  );

  it("builds the rows of 7,000 articles quickly", () => {
    const start = performance.now();
    const rows = buildRows(MANY, new Set(["docs"]));
    const took = performance.now() - start;
    expect(rows).toHaveLength(71);
    expect(took).toBeLessThan(500);
    const open = buildRows(
      MANY,
      new Set(["docs", ...Array.from({ length: 70 }, (_, i) => `docs/section-${i}`)]),
    );
    expect(open).toHaveLength(7071);
  });

  it("renders 2,000 open rows within seconds and marks each for lazy layout", async () => {
    const rows = buildRows(
      MANY.slice(0, 2000),
      new Set(["docs", ...Array.from({ length: 70 }, (_, i) => `docs/section-${i}`)]),
    );
    shown = { rows, onToggle: vi.fn() };
    const start = performance.now();
    render(<TestRouter pages={{ "/": TreeUnderTest }} />);
    const items = await screen.findAllByRole("treeitem");
    expect(performance.now() - start).toBeLessThan(5000);
    expect(items).toHaveLength(rows.length);
    // content-visibility: auto on each row lets the browser skip the layout of the ones off screen.
    expect(screen.getByRole("tree").className).toContain("content-visibility:auto");
  });
});
