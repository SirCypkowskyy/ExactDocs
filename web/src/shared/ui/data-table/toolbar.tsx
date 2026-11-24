import { X } from "lucide-react";
import { type ReactNode, useId } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button } from "../button";
import { messages } from "../messages";
import { Tag, TagList } from "../tags";
import { ColumnsMenu } from "./columns";
import { FacetedFilter } from "./faceted-filter";
import { SearchFilter } from "./search-filter";
import type { DataTableModel } from "./use-data-table";

/*
 * The table's toolbar (blocks-map §2.2), after the free shadcnblocks Data Table 1 (`data-table1`):
 * the global filter (`q`), one button per faceted filter, the Columns menu at the end, and under
 * them the active filters as `Tag` chips (with a remove button) and Clear all.
 */
export function DataTableToolbar<T>({
  model,
  search,
  children,
  columns = true,
}: {
  model: DataTableModel<T>;
  /** The search box's label and placeholder; leave out for a table with no text filter. */
  search?: { label: string; placeholder?: string } | undefined;
  /** More controls after the filters. */
  children?: ReactNode;
  /** Offer the Columns menu. */
  columns?: boolean;
}) {
  const id = useId();
  const t = useMessages(messages).dataTable;
  return (
    <div className="mb-4 flex flex-col gap-3">
      <search className="flex flex-wrap items-end gap-2">
        {search && (
          <SearchFilter
            id={`${id}-q`}
            label={search.label}
            placeholder={search.placeholder}
            value={model.q}
            onCommit={model.setQ}
            icon
            className="max-w-md"
          />
        )}
        {model.filters.length > 0 && (
          // biome-ignore lint/a11y/useSemanticElements: a group of buttons, not a form fieldset
          <div role="group" aria-label={t.filters} className="flex flex-wrap items-center gap-2">
            {model.filters.map((filter) => (
              <FacetedFilter key={filter.id} model={model} filter={filter} />
            ))}
          </div>
        )}
        {children}
        {columns && (
          // Below `md` rows are cards with their own few cells: no columns to choose.
          <div className="ml-auto max-md:hidden">
            <ColumnsMenu table={model.table} />
          </div>
        )}
      </search>
      <ActiveFilters model={model} />
    </div>
  );
}

interface Chip {
  key: string;
  title: string;
  value: string;
  mono?: boolean;
  remove: () => void;
}

/** One chip per picked value and per narrowing parameter; Clear all once there is any filter. */
export function ActiveFilters<T>({ model }: { model: DataTableModel<T> }) {
  const t = useMessages(messages).dataTable;
  const chips: Chip[] = [];
  for (const filter of model.filters) {
    const picked = model.selected(filter.id);
    for (const value of picked) {
      chips.push({
        key: `${filter.id}:${value}`,
        title: filter.title,
        value: filter.options.find((o) => o.value === value)?.label ?? value,
        remove: () =>
          model.setFilter(
            filter.id,
            picked.filter((v) => v !== value),
          ),
      });
    }
  }
  for (const param of model.params) {
    const value = model.param(param.id);
    if (value) {
      chips.push({
        key: param.id,
        title: param.title,
        value: param.format?.(value) ?? value,
        ...(param.mono && { mono: true }),
        remove: () => model.setParam(param.id, undefined),
      });
    }
  }
  if (!model.filtered) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {chips.length > 0 && (
        <TagList label={t.activeFilters}>
          {chips.map((chip) => (
            <li key={chip.key} className="reveal flex min-w-0">
              <Tag
                removeLabel={t.removeFilter(t.chip(chip.title, chip.value))}
                onRemove={chip.remove}
              >
                {chip.title}:{" "}
                <span className={cn("text-foreground", chip.mono && "font-mono")}>
                  {chip.value}
                </span>
              </Tag>
            </li>
          ))}
        </TagList>
      )}
      <Button variant="ghost" size="sm" onClick={model.clearFilters}>
        <X aria-hidden="true" data-icon-motion="turn" />
        {t.clearAll}
      </Button>
    </div>
  );
}
