import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Tag, TagList } from "./tags";
import { TooltipProvider } from "./tooltip";

describe("Tag", () => {
  it("toggles: a pressed button, one target", async () => {
    const onClick = vi.fn();
    render(
      <Tag pressed={false} onClick={onClick}>
        api
      </Tag>,
    );
    const chip = screen.getByRole("button", { name: "api" });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    expect(chip).toHaveClass("h-11");
    await userEvent.click(chip);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("removes: a chip in a named list with a remove button named after it", async () => {
    const onRemove = vi.fn();
    render(
      <TooltipProvider>
        <TagList label="Active filters">
          <li>
            <Tag removeLabel="Remove filter Tags: api" onRemove={onRemove}>
              Tags: api
            </Tag>
          </li>
        </TagList>
      </TooltipProvider>,
    );
    expect(screen.getByRole("list", { name: "Active filters" })).toHaveTextContent("Tags: api");
    await userEvent.click(screen.getByRole("button", { name: "Remove filter Tags: api" }));
    expect(onRemove).toHaveBeenCalledOnce();
  });

  it("is plain text without an action", () => {
    render(<Tag mono>/acme/web</Tag>);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("/acme/web")).toHaveClass("font-mono");
  });
});
