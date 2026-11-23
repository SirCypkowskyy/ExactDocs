import { act, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { DataTable, useServerTable } from "./data-table";

interface Row {
  id: string;
}

let renders = 0;
let bump: () => void = () => {};

/** Like the real lists: the rows are a new array on every render (`pages.flatMap(...)`). */
function Harness() {
  const [, setTick] = useState(0);
  bump = () => setTick((t) => t + 1);
  renders += 1;
  const rows: Row[] = [{ id: "a" }, { id: "b" }];
  const table = useServerTable({
    data: rows,
    columns: [{ accessorKey: "id", header: "ID" }],
    getRowId: (r) => r.id,
    sort: undefined,
    onSort: () => {},
  });
  return <DataTable table={table} label="Rows" loadingMore={false} />;
}

describe("a server-side table", () => {
  it("settles after a re-render even when its rows are a new array each time", async () => {
    render(<Harness />);
    expect(screen.getByRole("table", { name: "Rows" })).toBeInTheDocument();
    // A client-side page reset would queue a state update per new array: renders without end.
    for (let i = 0; i < 3; i++) {
      await act(async () => bump());
    }
    renders = 0;
    await act(async () => bump());
    await act(async () => await new Promise((r) => setTimeout(r, 50)));
    expect(renders).toBeLessThan(5);
  });
});
