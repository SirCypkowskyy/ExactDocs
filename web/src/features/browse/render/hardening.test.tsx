import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { grammarOf, highlight } from "./highlight";
import { createBudget, MAX_BLOCK, MAX_TOTAL } from "./limits";
import { Markdown, type Where } from "./markdown";
import { inertMdx } from "./parse";
import { classifyLink, rawUrl } from "./urls";

const where: Where = {
  path: "docs/a.md",
  title: "A",
  imageUrl: () => undefined,
  fileUrl: () => undefined,
  docLink: (p, h, children) => <a href={`/x?path=${p}${h}`}>{children}</a>,
};
const view = (source: string, extra: { mdx?: boolean; hash?: string; where?: Where } = {}) =>
  render(
    <Markdown
      source={source}
      mdx={extra.mdx ?? false}
      where={extra.where ?? where}
      hash={extra.hash ?? ""}
    />,
  );

afterEach(() => vi.restoreAllMocks());

describe("heading ids", () => {
  it("never collide with the app's own ids; the anchor stays the URL fragment", () => {
    const { container } = view("# root\n\n## sign-out-error\n");
    expect([...container.querySelectorAll("[id]")].map((e) => e.id)).toEqual([
      "doc-root",
      "doc-sign-out-error",
    ]);
    expect(container.querySelector("#root")).toBeNull();
    expect(container.querySelector('a[href="#sign-out-error"]')).not.toBeNull();
  });

  it("opens on the heading the bare chunk anchor names, and marks it", () => {
    const spy = vi.spyOn(Element.prototype, "scrollIntoView");
    const { container } = view("# Top\n\n## Install it\n\ntext\n\n## Other\n", {
      hash: "install-it",
    });
    const target = container.querySelector("#doc-install-it");
    expect(spy.mock.contexts.at(-1)).toBe(target);
    expect(target).toHaveClass("doc-target");
    expect(container.querySelector("#doc-other")).not.toHaveClass("doc-target");
  });

  it("ignores a fragment that is not a heading, or is malformed", () => {
    const spy = vi.spyOn(Element.prototype, "scrollIntoView");
    view("# A\n", { hash: "nothing-here" });
    view("# A\n", { hash: "%E0%A4%A" });
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("a callout keeps its content across renders", () => {
  const source = "!!! note\n    Body text\n\n    ```ts\n    const x = 1;\n    ```\n";
  it("does not remount its body when the article re-renders", () => {
    const { container, rerender } = view(source);
    const body = container.querySelector(".doc-callout-body p");
    const code = container.querySelector(".doc-callout-body pre");
    rerender(<Markdown source={source} mdx={false} where={{ ...where }} hash="" />);
    expect(container.querySelector(".doc-callout-body p")).toBe(body);
    expect(container.querySelector(".doc-callout-body pre")).toBe(code);
  });
  it("keeps a collapsible's open state", async () => {
    const { container, rerender } = view('??? tip "More"\n    Hidden.\n');
    const details = container.querySelector("details") as HTMLDetailsElement;
    details.open = true;
    rerender(
      <Markdown
        source={'??? tip "More"\n    Hidden.\n'}
        mdx={false}
        where={{ ...where }}
        hash=""
      />,
    );
    expect((container.querySelector("details") as HTMLDetailsElement).open).toBe(true);
  });
  it("does not number nodes across documents", () => {
    const a = renderToStaticMarkup(<Markdown source={source} mdx={false} where={where} />);
    const b = renderToStaticMarkup(<Markdown source={source} mdx={false} where={where} />);
    expect(a).toBe(b);
  });
});

describe("accessibility of callouts, tables and images", () => {
  it("says the kind of a titled callout to screen readers", () => {
    const { container } = view(
      '!!! warning "Rate limits"\n    100 a second.\n\n??? tip "More"\n    x\n',
    );
    expect(container.querySelector(".doc-warning .sr-only")?.textContent).toBe("Warning: ");
    expect(container.querySelector("summary .sr-only")?.textContent).toBe("Tip: ");
  });
  it("names a table by its first column", () => {
    view("| Field | Type |\n|---|---|\n| a | b |\n");
    expect(screen.getByRole("region", { name: "Table: Field" })).toBeInTheDocument();
  });
  it("says why an image is not shown", () => {
    view("![The chart](./c.png)");
    expect(screen.getByText("Image not shown: The chart")).toBeInTheDocument();
  });
});

describe("copy", () => {
  const code = "```bash\necho hi\n```\n";
  it("copies and says so in a status region", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    view(code);
    await userEvent.click(screen.getByRole("button", { name: /Copy/ }));
    expect(writeText).toHaveBeenCalledWith("echo hi");
    expect(await screen.findByRole("status")).toHaveTextContent("Copied");
    vi.unstubAllGlobals();
  });
  it("selects the code and says what to press where the clipboard API is missing", async () => {
    vi.stubGlobal("navigator", {});
    const { container } = view(code);
    fireEvent.click(screen.getByRole("button", { name: /Copy/ }));
    expect(await screen.findByRole("status")).toHaveTextContent("Press Ctrl+C");
    expect(window.getSelection()?.toString()).toBe(container.querySelector("pre")?.textContent);
    vi.unstubAllGlobals();
  });
  it("says so when copying fails", async () => {
    vi.stubGlobal("navigator", {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("no")) },
    });
    view(code);
    await userEvent.click(screen.getByRole("button", { name: /Copy/ }));
    expect(await screen.findByRole("status")).toHaveTextContent("Copy failed");
    vi.unstubAllGlobals();
  });
});

describe("MDX fragments", () => {
  it("one block for MDX lines that only blank lines separate, labelled mdx", () => {
    const out = inertMdx(
      'import A from "a";\n\nexport const b = 1;\n\n<Tabs>\n\nText.\n\n</Tabs>\n',
    );
    expect(out).toBe(
      '````mdx\nimport A from "a";\n\nexport const b = 1;\n\n<Tabs>\n````\n\nText.\n\n````mdx\n</Tabs>\n````\n',
    );
  });
  it("leaves fences and prose alone", () => {
    const text = "Intro\n\n```jsx\n<Tabs>\n```\n\nOutro\n";
    expect(inertMdx(text)).toBe(text);
  });
});

describe("prototype names and URL schemes", () => {
  it("are never a grammar, a host or a link", async () => {
    for (const name of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
      expect(grammarOf(name)).toBeUndefined();
      expect(rawUrl(name, "https://x.test/a/b", "a".repeat(40), "p.png")).toBeUndefined();
      expect(await highlight("x", name)).toBeUndefined();
    }
  });
  it("only https://, http:// and mailto: leave the app", () => {
    for (const bad of ["https:evil.test", "http:evil.test", "HTTPS:/evil.test"]) {
      expect(classifyLink("a.md", bad).kind).not.toBe("external");
    }
    expect(classifyLink("a.md", "HTTPS://example.com").kind).toBe("external");
  });
});

describe("large articles stay bounded", () => {
  it("spends a per-block and a per-article highlighting budget", () => {
    const budget = createBudget();
    expect(budget.take(MAX_BLOCK + 1)).toBe(false);
    let taken = 0;
    while (budget.take(10_000)) taken += 10_000;
    expect(taken).toBe(MAX_TOTAL);
    expect(budget.take(1)).toBe(false);
  });

  it("does not highlight a huge block", async () => {
    const started = performance.now();
    expect(await highlight("x = 1\n".repeat(80_000), "python")).toBeUndefined();
    expect(performance.now() - started).toBeLessThan(100);
  });

  it("renders thousands of blocks quickly, and highlights only what the budget allows", async () => {
    const line = `const a = ${"1".repeat(90)};\n`;
    const block = `\`\`\`js\n${line}\`\`\`\n\n`;
    const source = block.repeat(3000);
    const started = performance.now();
    const html = renderToStaticMarkup(<Markdown source={source} mdx={false} where={where} />);
    expect(performance.now() - started).toBeLessThan(5000);
    expect(html.match(/<figure/g)).toHaveLength(3000);
    // each block is about 100 characters: the budget covers 2000 of them, never all 3000
    const budget = createBudget();
    let covered = 0;
    for (let i = 0; i < 3000; i++) if (budget.take(line.length)) covered++;
    expect(covered).toBeLessThan(3000);
    await act(async () => {});
  });
});

describe("task lists", () => {
  it("are checkboxes, not text", () => {
    const { container } = view("- [x] Done\n- [ ] Todo\n- [x]not a task\n");
    expect(screen.getByRole("img", { name: "Done" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Not done" })).toBeInTheDocument();
    expect(container.querySelectorAll(".doc-task")).toHaveLength(2);
    expect(container.textContent).toContain("[x]not a task");
  });
});
