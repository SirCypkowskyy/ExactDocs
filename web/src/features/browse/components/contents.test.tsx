import { render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it } from "vitest";
import { TestRouter } from "@/shared/lib/test-router";
import { ContentsDisclosure, ContentsRail } from "./contents";

/** The rendered article: what the Markdown renderer leaves in the DOM (`.doc` and its headings). */
function Article({ headings }: { headings: [2 | 3 | 1, string][] }) {
  return (
    <div className="doc">
      {headings.map(([level, text]) => (
        <h2 key={text} id={`doc-${text.toLowerCase()}`} className={`doc-h doc-h${level}`}>
          {text}
          <a className="doc-anchor" href={`#${text.toLowerCase()}`}>
            #
          </a>
        </h2>
      ))}
    </div>
  );
}

let headings: [2 | 3 | 1, string][] = [];
let which: "rail" | "disclosure" = "rail";
const article = createRef<HTMLDivElement>();

function PageUnderTest() {
  const Contents = which === "rail" ? ContentsRail : ContentsDisclosure;
  return (
    <>
      <div ref={article}>
        <Article headings={headings} />
      </div>
      <Contents
        article={article}
        owner="fixture"
        repo="docs-repo"
        version="v1.4.0"
        path="docs/guide/resilience.md"
        tags={undefined}
      />
    </>
  );
}

function renderContents(list: [2 | 3 | 1, string][], kind: "rail" | "disclosure") {
  headings = list;
  which = kind;
  render(<TestRouter pages={{ "/": PageUnderTest }} />);
}

describe("On this page", () => {
  it("lists the h2 and h3 sections, without the heading's own # link", async () => {
    renderContents(
      [
        [2, "Retries"],
        [3, "Backoff"],
        [2, "Timeouts"],
        [1, "Not listed"],
      ],
      "rail",
    );
    const nav = await screen.findByRole("navigation", { name: "On this page" });
    const links = nav.querySelectorAll("a");
    expect([...links].map((a) => a.textContent)).toEqual(["Retries", "Backoff", "Timeouts"]);
    expect(links[0]).toHaveAttribute(
      "href",
      expect.stringContaining("path=docs%2Fguide%2Fresilience.md"),
    );
    expect(links[0]?.getAttribute("href")).toMatch(/#retries$/);
  });

  it("is left out for an article with fewer than two sections", async () => {
    renderContents([[2, "Only"]], "rail");
    await waitFor(() => expect(document.querySelector(".doc")).not.toBeNull());
    expect(screen.queryByRole("navigation", { name: "On this page" })).toBeNull();
  });

  it("folds the same list under a disclosure that names the section count", async () => {
    renderContents(
      [
        [2, "Retries"],
        [2, "Timeouts"],
      ],
      "disclosure",
    );
    const summary = await screen.findByText("2 sections");
    expect(summary.closest("summary")).toHaveTextContent("On this page");
    expect(summary.closest("details")).not.toHaveAttribute("open");
  });
});
