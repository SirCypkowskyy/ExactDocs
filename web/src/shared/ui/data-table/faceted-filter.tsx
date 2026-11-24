import { Check, ListFilter } from "lucide-react";
import { formatNumber, useLanguage, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Badge } from "../badge";
import { Button } from "../button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "../command";
import { messages } from "../messages";
import { Popover, PopoverContent, PopoverTrigger } from "../popover";
import type { DataTableModel, TableFilter } from "./use-data-table";

/*
 * A faceted filter (after shadcn/ui's data-table guide, MIT): an outline button that names the
 * filter and counts what is picked ("State · 2"), opening a Popover with a Command list of the
 * values to tick. Several values mean "any of these"; a `single` filter (a date preset) takes one.
 * In client mode each value shows how many rows have it.
 */
export function FacetedFilter<T>({
  model,
  filter,
}: {
  model: DataTableModel<T>;
  filter: TableFilter;
}) {
  const t = useMessages(messages).dataTable;
  const language = useLanguage();
  const picked = model.selected(filter.id);
  const on = new Set(picked);
  const counts = model.counts(filter.id);
  const toggle = (value: string) => {
    if (filter.single) {
      model.setFilter(filter.id, on.has(value) ? [] : [value]);
      return;
    }
    const next = new Set(on);
    if (!next.delete(value)) next.add(value);
    // Kept in the options' order, so the URL is the same whatever the order of the clicks.
    model.setFilter(
      filter.id,
      filter.options.map((o) => o.value).filter((v) => next.has(v)),
    );
  };
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          aria-label={t.filterSelected(filter.title, picked.length)}
          className={cn(picked.length > 0 && "border-muted-foreground/50")}
        >
          <ListFilter aria-hidden="true" data-icon-motion="tilt" />
          {filter.title}
          {picked.length > 0 && (
            <Badge count aria-hidden="true" className="bg-accent text-foreground">
              {formatNumber(picked.length, language)}
            </Badge>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-0">
        <Command>
          <CommandInput placeholder={filter.title} aria-label={t.filterOptions(filter.title)} />
          <CommandList aria-label={filter.title}>
            <CommandEmpty>{t.noOptions}</CommandEmpty>
            <CommandGroup>
              {filter.options.map((option) => {
                const checked = on.has(option.value);
                const count = counts?.get(option.value);
                const Icon = option.icon;
                return (
                  <CommandItem
                    key={option.value}
                    value={option.label}
                    keywords={[option.value]}
                    aria-checked={checked}
                    onSelect={() => toggle(option.value)}
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        "flex size-4 flex-none items-center justify-center border transition-colors duration-(--dur-fast)",
                        filter.single ? "rounded-full" : "rounded-sm",
                        checked
                          ? "border-selection bg-selection text-route-foreground"
                          : "border-muted-foreground bg-background",
                      )}
                    >
                      {checked &&
                        (filter.single ? (
                          <span className="size-1.5 rounded-full bg-current" />
                        ) : (
                          <Check className="size-3! text-route-foreground!" strokeWidth={3} />
                        ))}
                    </span>
                    {Icon && <Icon aria-hidden="true" />}
                    <span className="min-w-0 flex-1 truncate">{option.label}</span>
                    {count !== undefined && (
                      <span className="num ml-auto text-small text-muted-foreground">
                        {formatNumber(count, language)}
                      </span>
                    )}
                  </CommandItem>
                );
              })}
            </CommandGroup>
            {picked.length > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem
                    value={`__clear__ ${t.clearFacet}`}
                    onSelect={() => model.setFilter(filter.id, [])}
                    className="justify-center"
                  >
                    {t.clearFacet}
                  </CommandItem>
                </CommandGroup>
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
