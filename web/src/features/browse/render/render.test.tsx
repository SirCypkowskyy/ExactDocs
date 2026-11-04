import { render } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import admonitions from "./fixtures/admonitions.md?raw";
import rich from "./fixtures/rich.md?raw";
import widget from "./fixtures/widget.mdx.txt?raw";
import xss from "./fixtures/xss.md?raw";
import { grammarOf, highlight } from "./highlight";
import { Markdown, type Where } from "./markdown";
import { tokensOf } from "./tokens";
import { classifyLink, rawUrl, repoPath } from "./urls";

const SHA = "a".repeat(40);
const where = (over: Partial<Where> = {}): Where => ({
  path: "docs/guide/start.md",
  title: "Payments quickstart",
  imageUrl: (p) => rawUrl("github", "https://github.com/acme/payments", SHA, p),
  fileUrl: () => undefined,
  docLink: (p, h, children) => (
    <a href={`/libraries/acme/payments?path=${encodeURIComponent(p)}${h}`}>{children}</a>
  ),
  ...over,
});
// Static markup: the code blocks are plain here, their colours arrive after a lazy grammar.
const html = (source: string, mdx = false, w = where()) =>
  renderToStaticMarkup(<Markdown source={source} mdx={mdx} where={w} />)
    .replace(/<svg.*?<\/svg>/g, "<svg/>") // icons are not what is being tested
    .replace(
      /(<\/(?:p|h\d|li|ul|ol|figure|section|div|details|summary|blockquote|pre|tr|thead|tbody)>)/g,
      "$1\n",
    );

describe("fixture articles", () => {
  it("a rich article, public library", () => {
    expect(html(rich)).toMatchSnapshot();
  });
  it("the same article, private library: images are alt text", () => {
    expect(html(rich, false, where({ imageUrl: () => undefined }))).toMatchSnapshot();
  });
  it("both admonition syntaxes", () => {
    expect(html(admonitions)).toMatchSnapshot();
  });
  it("an MDX article", () => {
    expect(html(widget, true)).toMatchSnapshot();
  });
});

describe("admonitions", () => {
  const dom = () => {
    const { container } = render(<Markdown source={admonitions} mdx={false} where={where()} />);
    return { container, notes: [...container.querySelectorAll(".doc-callout")] };
  };

  it("renders !!! and > [!KIND] blocks as callouts", () => {
    const { notes } = dom();
    const titles = notes.map((n) => n.querySelector(".doc-callout-title, summary")?.textContent);
    expect(titles).toEqual([
      "Note",
      "Tip: Use the sandbox",
      "Warning: Rate limits",
      "Danger",
      "Note: Collapsed by default",
      "Tip: Open by default",
      "Note: Unknown kinds are notes",
      "Note",
      "Tip",
      "Important",
      "Warning",
      "Caution",
    ]);
  });
  it("maps every kind to one of four looks", () => {
    const { notes } = dom();
    const looks = notes.map((n) =>
      [...n.classList].find((c) => /^doc-(note|tip|warning|danger)$/.test(c)),
    );
    expect(looks).toEqual([
      "doc-note",
      "doc-tip",
      "doc-warning",
      "doc-danger",
      "doc-note",
      "doc-tip",
      "doc-note",
      "doc-note",
      "doc-tip",
      "doc-warning",
      "doc-warning",
      "doc-danger",
    ]);
  });
  it("keeps plain quotes and unknown GitHub kinds as quotes, and Markdown inside a callout", () => {
    const { container, notes } = dom();
    expect(container.querySelectorAll("blockquote")).toHaveLength(2);
    expect(notes[1]?.querySelectorAll("li")).toHaveLength(2);
    expect(notes[0]?.querySelector("strong")?.textContent).toBe("bold");
    expect(notes[5]?.tagName).toBe("DETAILS");
    expect((notes[5] as HTMLDetailsElement).open).toBe(true);
    expect((notes[4] as HTMLDetailsElement).open).toBe(false);
  });
});

describe("MDX stays inert", () => {
  const dom = () =>
    render(<Markdown source={widget} mdx where={where({ title: "Widgets" })} />).container;
  it("shows imports, exports and components as code", () => {
    const container = dom();
    const code = [...container.querySelectorAll("pre code")].map((c) => c.textContent);
    expect(code.join("\n")).toContain('import { Tabs, Tab } from "@site/components";');
    expect(code.join("\n")).toContain("export const meta");
    expect(code.join("\n")).toContain('<Tabs groupId="pm">');
    expect(container.querySelector("tabs, tab, banner")).toBeNull();
  });
  it("still renders the Markdown around them, and `{expressions}` are text", () => {
    const container = dom();
    expect(container.querySelector("strong")?.textContent).toBe("Markdown");
    expect(container.textContent).toContain("{1 + 1}");
    expect(container.querySelector("code")).not.toBeNull();
  });
});

describe("untrusted input", () => {
  const dom = () => render(<Markdown source={xss} mdx={false} where={where()} />).container;

  it("never makes a script, frame, style, form or svg element", () => {
    const container = dom();
    expect(
      container.querySelectorAll(
        "script, iframe, object, embed, style, form, input, svg:not(.lucide)",
      ),
    ).toHaveLength(0);
  });
  it("never sets an event handler", () => {
    const container = dom();
    const attrs = [...container.querySelectorAll("*")].flatMap((el) =>
      [...el.attributes].map((a) => [el.tagName.toLowerCase(), a.name] as const),
    );
    expect(attrs.filter(([, name]) => name.startsWith("on"))).toEqual([]);
  });
  it("only links to https, mailto and the page itself", () => {
    const container = dom();
    const hrefs = [...container.querySelectorAll("a[href]")].map(
      (a) => a.getAttribute("href") ?? "",
    );
    expect(hrefs.filter((h) => !/^(https:\/\/example\.com|#)/.test(h))).toEqual([]);
    expect(hrefs).toContain("https://example.com");
  });
  it("never loads an image from anywhere but the commit", () => {
    const container = dom();
    const srcs = [...container.querySelectorAll("img")].map((i) => i.getAttribute("src"));
    expect(srcs).toEqual([
      `https://raw.githubusercontent.com/acme/payments/${SHA}/docs/guide/a.png`,
    ]);
  });
  it("shows the raw HTML as text", () => {
    const container = dom();
    expect(container.textContent).toContain("<script>window.__pwned = 1</script>");
    expect(container.textContent).toContain("<iframe");
    expect(container.textContent).toContain("[js link](javascript:alert(7))");
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  });
  it("renders a heading's markup as text", () => {
    const container = dom();
    const heading = container.querySelector("#doc-heading");
    expect(heading?.textContent).toContain("<img src=x onerror=alert(15)>");
    expect(heading?.querySelector("img")).toBeNull();
  });
});

describe("links and images", () => {
  it("resolves repository paths against the article's folder and never leaves the repository", () => {
    expect(repoPath("docs/guide/start.md", "./img/a.png")).toBe("docs/guide/img/a.png");
    expect(repoPath("docs/guide/start.md", "../a.png?raw=1#x")).toBe("docs/a.png");
    expect(repoPath("docs/guide/start.md", "/README.md")).toBe("README.md");
    expect(repoPath("docs/start.md", "../../x.png")).toBeUndefined();
    expect(repoPath("docs/start.md", "%E0%A4%A")).toBeUndefined();
  });
  it("classifies links", () => {
    expect(classifyLink("a.md", "#x")).toEqual({ kind: "hash", href: "#x" });
    expect(classifyLink("a/b.md", "c.mdx#d")).toEqual({ kind: "doc", path: "a/c.mdx", hash: "#d" });
    expect(classifyLink("a.md", "x.png")).toEqual({ kind: "file", path: "x.png" });
    expect(classifyLink("a.md", "mailto:a@b.c").kind).toBe("external");
    for (const bad of ["javascript:x", "data:text/html,x", "//evil.test/x", "ftp://x"]) {
      expect(classifyLink("a.md", bad).kind).toBe("none");
    }
  });
  it("builds the host's raw URL at the commit", () => {
    const p = "docs/my image.png";
    expect(rawUrl("github", "https://github.com/a/b", SHA, p)).toBe(
      `https://raw.githubusercontent.com/a/b/${SHA}/docs/my%20image.png`,
    );
    expect(rawUrl("gitlab", "git@gitlab.com:a/b.git", SHA, p)).toBe(
      `https://gitlab.com/a/b/-/raw/${SHA}/docs/my%20image.png`,
    );
    expect(rawUrl("gitea", "https://git.example.org/a/b", SHA, p)).toBe(
      `https://git.example.org/a/b/raw/commit/${SHA}/docs/my%20image.png`,
    );
    expect(rawUrl("github", "https://ghe.corp.test/a/b", SHA, p)).toBe(
      `https://ghe.corp.test/a/b/raw/${SHA}/docs/my%20image.png`,
    );
    expect(rawUrl("github", "file:///srv/x", SHA, p)).toBeUndefined();
    expect(rawUrl("unknown", "https://x.test/a/b", SHA, p)).toBeUndefined();
    expect(rawUrl("github", "https://github.com/a/b", "main", p)).toBeUndefined();
  });
  it("private: an image is its alt text", () => {
    const { container } = render(
      <Markdown
        source="![A diagram](./d.png)"
        mdx={false}
        where={where({ imageUrl: () => undefined })}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toBe("Image not shown: A diagram");
  });
  it("links another article through the app's own link", () => {
    const { container } = render(
      <Markdown source="[x](./auth.md#keys)" mdx={false} where={where()} />,
    );
    expect(container.querySelector("a")?.getAttribute("href")).toBe(
      "/libraries/acme/payments?path=docs%2Fguide%2Fauth.md#keys",
    );
  });
});

describe("highlighting", () => {
  it("knows the common fence names and their aliases", () => {
    expect(grammarOf("ts")).toBe("typescript");
    expect(grammarOf("SH")).toBe("bash");
    expect(grammarOf("yml")).toBe("yaml");
    expect(grammarOf("nolang-here")).toBeUndefined();
  });
  it("colours code and turns its markup into elements, not HTML", async () => {
    const markup = await highlight('const x = "<b>&</b>"; // hi', "ts");
    const { container } = render(<code>{tokensOf(markup ?? "")}</code>);
    expect(container.querySelector(".hljs-keyword")?.textContent).toBe("const");
    expect(container.querySelector(".hljs-string")?.textContent).toBe('"<b>&</b>"');
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toBe('const x = "<b>&</b>"; // hi');
  });
  it("leaves an unknown language alone", async () => {
    expect(await highlight("x", "klingon")).toBeUndefined();
  });
});
