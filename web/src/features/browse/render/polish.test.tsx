import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { Markdown, type Where } from "./markdown";

const where: Where = {
  path: "docs/a.md",
  title: "A",
  imageSources: () => [],
  fileUrl: () => undefined,
  docLink: (p, h, children) => <a href={`/x?path=${p}${h}`}>{children}</a>,
};

beforeEach(() => setPreferences({ language: "pl" }));
afterEach(() => {
  resetPreferences();
  vi.unstubAllGlobals();
});

describe("the renderer in Polish", () => {
  it("labels what it adds in Polish and keeps the document's words", () => {
    const source = [
      "## Setup",
      "> [!WARNING]\n> Mind the limits.",
      '!!! danger "Do not share keys"\n    Ever.',
      "| Name | Value |\n| --- | --- |\n| a | 1 |",
      "- [x] Done already\n- [ ] Still to do",
      "![The chart](https://example.com/chart.png)",
      "```\nplain\n```",
    ].join("\n\n");
    const { container } = render(<Markdown source={source} mdx={false} where={where} />);
    expect(screen.getByRole("link", { name: "Link do nagłówka „Setup”" })).toBeInTheDocument();
    // A callout's name as the file writes it is the document's; the type said before a title is ours.
    const [warning, danger] = [...container.querySelectorAll(".doc-callout-title")];
    expect(warning).toHaveTextContent("Warning");
    expect(danger).toHaveTextContent("Niebezpieczeństwo: Do not share keys");
    expect(screen.getByRole("region", { name: "Tabela: Name" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Wykonane" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Niewykonane" })).toBeInTheDocument();
    expect(screen.getByText("Obraz niedostępny: The chart")).toBeInTheDocument();
    const block = container.querySelector("figure.doc-code") as HTMLElement;
    expect(within(block).getByText("Tekst")).toBeInTheDocument();
    expect(within(block).getByRole("button")).toHaveTextContent("Kopiujkod");
  });

  it("says what to press when there is no clipboard, in Polish", async () => {
    vi.stubGlobal("navigator", {});
    render(<Markdown source={"```sh\necho hi\n```"} mdx={false} where={where} />);
    fireEvent.click(screen.getByRole("button", { name: /Kopiuj/ }));
    expect(await screen.findByRole("status")).toHaveTextContent("Naciśnij Ctrl+C");
  });
});
