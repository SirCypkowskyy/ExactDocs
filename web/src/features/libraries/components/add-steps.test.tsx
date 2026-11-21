import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AddSteps } from "./add-steps";

describe("add steps", () => {
  it("marks the step the person is on", () => {
    render(<AddSteps phase="choose" />);
    const current = screen.getAllByRole("listitem").find((li) => li.ariaCurrent === "step");
    expect(current).toHaveTextContent("Choose version");
    expect(screen.getByText("Check repository")).toBeInTheDocument();
  });

  it("says a step is done and when the import failed", () => {
    const { rerender } = render(<AddSteps phase="import" />);
    expect(screen.getAllByText("(done)")).toHaveLength(3);
    rerender(<AddSteps phase="failed" />);
    expect(screen.getByText("(failed)")).toBeInTheDocument();
  });
});
