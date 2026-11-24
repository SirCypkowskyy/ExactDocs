import { ChevronDown, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import { formatNumber, useLanguage, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button, IconButton } from "../button";
import { messages } from "../messages";
import { select } from "../recipes";
import { Tooltip } from "../tooltip";
import type { PageSize } from "./table-search";
import type { DataTableModel } from "./use-data-table";

/*
 * The pagination bar (blocks-map §2.2), after the free shadcnblocks Data Table 1 (`data-table1`)
 * and shadcn/ui's data-table guide (MIT): "21–40 of 233", rows per page, "Page 2 of 12", then
 * First, Previous, the numbered pages, Next and Last (numbers and Last where a page is reached in
 * one step: client mode, or a source that pages by offset). A live region says which page is
 * shown after a move; the table's top scrolls into view and focus stays on the button (an end
 * that cannot be passed is `aria-disabled`, not disabled, so focus is not lost).
 *
 * The API's offset stops at 10,000 rows (`model.lastJump`): a page past it is reached with Next
 * or Previous from its neighbour, never by a jump, so Last and the numbers past it are
 * `aria-disabled` and say why in their name and tooltip, and a line under the bar says it for
 * touch screens, which show no tooltips.
 */

/** Page numbers around `page`, at most seven slots, both ends kept; `null` is a gap ("…"). */
function pageWindow(page: number, count: number): (number | null)[] {
  if (count <= 7) return Array.from({ length: count }, (_, i) => i + 1);
  if (page <= 4) return [1, 2, 3, 4, 5, null, count];
  if (page >= count - 3) return [1, null, count - 4, count - 3, count - 2, count - 1, count];
  return [1, null, page - 1, page, page + 1, null, count];
}

const blockedLook =
  "aria-disabled:cursor-not-allowed aria-disabled:bg-transparent aria-disabled:opacity-40";
const numberLook = "num w-auto min-w-11 px-2 fine:min-w-8";

export function DataTablePagination<T>({ model }: { model: DataTableModel<T> }) {
  const t = useMessages(messages).dataTable;
  const language = useLanguage();
  const id = useId();
  const [said, setSaid] = useState("");
  if (model.status !== "ready" || !model.total) return null;
  const { page, pageCount, offset, rows, total, lastJump } = model;
  /** Within the API's offset, or one step away (Previous, Next): a single request. */
  const reachable = (target: number) => target <= lastJump || Math.abs(target - page) <= 1;
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
      className={blockedLook}
      onClick={() => {
        if (!blocked) go(target);
      }}
    >
      {icon}
    </IconButton>
  );
  const number = (n: number) => {
    if (n === page) {
      return (
        <Button
          key={n}
          variant="outline"
          size="icon-sm"
          aria-label={t.page(n)}
          aria-current="page"
          className={numberLook}
        >
          {formatNumber(n, language)}
        </Button>
      );
    }
    const blocked = !reachable(n);
    const label = blocked ? t.outOfReach(t.page(n), lastJump) : t.page(n);
    const button = (
      <Button
        key={n}
        variant="ghost"
        size="icon-sm"
        aria-label={label}
        aria-disabled={blocked || undefined}
        className={cn(numberLook, "font-normal", blockedLook)}
        onClick={() => {
          if (!blocked) go(n);
        }}
      >
        {formatNumber(n, language)}
      </Button>
    );
    // A number names itself; only one out of reach needs a tooltip, to say why.
    return blocked ? (
      <Tooltip key={n} label={label}>
        {button}
      </Tooltip>
    ) : (
      button
    );
  };
  const lastOutOfReach = page < pageCount && !reachable(pageCount);
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
        <div className="ml-auto flex items-center gap-1">
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
          {model.canJump && pageCount > 1 && (
            // Phones keep the arrows and "Page 2 of 12": seven numbers do not fit beside them.
            <div className="hidden items-center gap-1 text-foreground sm:flex">
              {pageWindow(page, pageCount).map((n, i) =>
                n === null ? (
                  <span
                    // A gap is known by its side of the current page (at most one each).
                    key={i < 3 ? "gap-before" : "gap-after"}
                    aria-hidden="true"
                    className="px-1 text-muted-foreground"
                  >
                    …
                  </span>
                ) : (
                  number(n)
                ),
              )}
            </div>
          )}
          {nav(
            t.nextPage,
            page + 1,
            <ChevronRight aria-hidden="true" data-icon-motion="forward" />,
            page >= pageCount,
          )}
          {model.canJump &&
            nav(
              lastOutOfReach ? t.outOfReach(t.lastPage, lastJump) : t.lastPage,
              pageCount,
              <ChevronsRight aria-hidden="true" data-icon-motion="forward" />,
              page >= pageCount || lastOutOfReach,
            )}
        </div>
      </div>
      {model.canJump && lastJump < pageCount && (
        <p className="basis-full sm:text-right">{t.jumpsStop(lastJump)}</p>
      )}
      <p role="status" className="sr-only">
        {said}
      </p>
    </nav>
  );
}
