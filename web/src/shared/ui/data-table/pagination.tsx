import { ChevronDown, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { IconButton } from "../button";
import { messages } from "../messages";
import { select } from "../recipes";
import type { PageSize } from "./table-search";
import type { DataTableModel } from "./use-data-table";

/*
 * The pagination bar (blocks-map §2.2), after the free shadcnblocks Data Table 1 (`data-table1`)
 * and shadcn/ui's data-table guide (MIT): "21–40 of 233", rows per page, "Page 2 of 12" and
 * First, Previous, Next (and Last, where a page can be reached in one step) as icon buttons with
 * tooltips. A live region says which page is shown after a move; the table's top scrolls into view
 * and focus stays on the button (an end that cannot be passed is `aria-disabled`, not disabled,
 * so focus is not lost).
 */
export function DataTablePagination<T>({ model }: { model: DataTableModel<T> }) {
  const t = useMessages(messages).dataTable;
  const id = useId();
  const [said, setSaid] = useState("");
  if (model.status !== "ready" || !model.total) return null;
  const { page, pageCount, offset, rows, total } = model;
  const go = (target: number) => {
    if (target < 1 || target > pageCount || target === page) return;
    model.goTo(target);
    setSaid(t.pageOf(target, pageCount));
    const frame = model.frameRef.current;
    if (frame && frame.getBoundingClientRect().top < 0) frame.scrollIntoView({ block: "start" });
  };
  const nav = (label: string, target: number, icon: ReactNode, blocked: boolean) => (
    <IconButton
      label={label}
      size="icon-sm"
      aria-disabled={blocked || undefined}
      className="aria-disabled:cursor-not-allowed aria-disabled:bg-transparent aria-disabled:opacity-40"
      onClick={() => {
        if (!blocked) go(target);
      }}
    >
      {icon}
    </IconButton>
  );
  return (
    <nav
      aria-label={t.pagination}
      className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 pt-4 text-small text-muted-foreground"
    >
      <p className="num">{t.range(offset + 1, offset + rows.length, total)}</p>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        {model.sizes.length > 1 && (
          <div className="flex items-center gap-2">
            <label htmlFor={`${id}-size`}>{t.rowsPerPage}</label>
            <div className="relative">
              <select
                id={`${id}-size`}
                value={model.size}
                onChange={(e) => model.setSize(Number(e.target.value) as PageSize)}
                className={cn(select, "w-20 text-foreground")}
              >
                {model.sizes.map((size) => (
                  <option key={size} value={size}>
                    {size}
                  </option>
                ))}
              </select>
              <ChevronDown
                aria-hidden="true"
                className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2"
              />
            </div>
          </div>
        )}
        <p className="num">{t.pageOf(page, pageCount)}</p>
        <div className="flex items-center gap-1">
          {nav(
            t.firstPage,
            1,
            <ChevronsLeft aria-hidden="true" data-icon-motion="back" />,
            page <= 1,
          )}
          {nav(
            t.previousPage,
            page - 1,
            <ChevronLeft aria-hidden="true" data-icon-motion="back" />,
            page <= 1,
          )}
          {nav(
            t.nextPage,
            page + 1,
            <ChevronRight aria-hidden="true" data-icon-motion="forward" />,
            page >= pageCount,
          )}
          {model.canJump &&
            nav(
              t.lastPage,
              pageCount,
              <ChevronsRight aria-hidden="true" data-icon-motion="forward" />,
              page >= pageCount,
            )}
        </div>
      </div>
      <p role="status" className="sr-only">
        {said}
      </p>
    </nav>
  );
}
