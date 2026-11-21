import { describe, expect, it } from "vitest";
import { type Block, isCut, snippetBlocks } from "./snippet";

const text = (block: Block | undefined) =>
  block?.kind === "code"
    ? block.lines.map((l) => l.spans.map((s) => s.text).join("")).join("\n")
    : (block?.spans.map((s) => s.text).join("") ?? "");

describe("search snippets without markup", () => {
  it("drops heading lines and joins the prose", () => {
    const blocks = snippetBlocks("### retry_policy\n\nPass the policy\nto the client.", []);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.kind).toBe("text");
    expect(text(blocks[0])).toBe("Pass the policy to the client.");
  });

  it("turns a fence into code lines, without the fence", () => {
    const blocks = snippetBlocks("Call it:\n\n```python\nclient = Client()\nclient.run()\n```", []);
    expect(blocks.map((b) => b.kind)).toEqual(["text", "code"]);
    expect(text(blocks[1])).toBe("client = Client()\nclient.run()");
  });

  it("keeps a cut fence (no closing line) as code", () => {
    const blocks = snippetBlocks("```js\nconst a = 1", []);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.kind).toBe("code");
    expect(text(blocks[0])).toBe("const a = 1");
  });

  it("shows a table's rows as code and drops its rule", () => {
    const blocks = snippetBlocks("| a | b |\n| --- | :-: |\n| 1 | 2 |", []);
    expect(blocks).toHaveLength(1);
    expect(text(blocks[0])).toBe("| a | b |\n| 1 | 2 |");
  });

  it("reads a callout as a quote with its label", () => {
    const blocks = snippetBlocks("> [!NOTE]\n> Charges stay safe\n> to repeat.", []);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: "quote", label: "Note" });
    expect(text(blocks[0])).toBe("Charges stay safe to repeat.");
  });

  it("marks inline code and drops the backticks", () => {
    const [block] = snippetBlocks("Pass `retry_policy` here", []);
    expect(block?.kind === "text" && block.spans.map((s) => [s.text, s.code])).toEqual([
      ["Pass ", false],
      ["retry_policy", true],
      [" here", false],
    ]);
  });

  it("keeps every match where it was, across the markup it removes", () => {
    const source = "### Retry\n\nPass `retry_policy` to it";
    const start = source.indexOf("retry_policy");
    const [block] = snippetBlocks(source, [{ start, end: start + "retry_policy".length }]);
    const hits = block?.kind === "text" ? block.spans.filter((s) => s.hit) : [];
    expect(hits).toEqual([{ key: start, text: "retry_policy", hit: true, code: true }]);
  });

  it("knows a snippet that stops mid-sentence", () => {
    expect(isCut("client = Client(token=x, retry_policy=RetryPolicy(max_retries=3")).toBe(true);
    expect(isCut("It is never repeated.")).toBe(false);
  });
});
