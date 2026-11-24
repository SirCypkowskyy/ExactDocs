import { CalendarRange, Check } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import type { DataTableModel } from "@/shared/ui/data-table/use-data-table";
import { Input } from "@/shared/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover";
import { messages } from "../messages";
import { parseRange, rangeParam } from "../model/access-log";

/*
 * The access log's custom dates (blocks-map §2.2: dates are presets, 24 h, 7 d, 30 d, and custom).
 * The presets are a single-choice facet (`when`); this popover writes the same parameter as a
 * range of days, `from..to`, either end open. The facet then lists the range as its picked value,
 * so the chip, Clear all and the facet's own Clear treat it like a preset.
 */

/** The "Custom dates" button and its form: two days, both included, in this browser's zone. */
export function CustomDates<T>({ model }: { model: DataTableModel<T> }) {
  const id = useId();
  const t = useMessages(messages).list;
  const [picked] = model.selected("when");
  const range = picked ? parseRange(picked) : undefined;
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [error, setError] = useState<string>();

  // Every opening starts from the range in the URL (or empty fields).
  const onOpenChange = (next: boolean) => {
    if (next) {
      setFrom(range?.from ?? "");
      setTo(range?.to ?? "");
      setError(undefined);
    }
    setOpen(next);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!from && !to) return setError(t.rangeEmpty);
    if (from && to && from > to) return setError(t.rangeBackwards);
    model.setFilter("when", [rangeParam({ from: from || undefined, to: to || undefined })]);
    setOpen(false);
  };
  const errorId = `${id}-error`;
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className={cn(range && "border-muted-foreground/50")}>
          <CalendarRange aria-hidden="true" data-icon-motion="tilt" />
          {t.customDates}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <form
          aria-labelledby={`${id}-title`}
          className="flex flex-col gap-3"
          noValidate
          onSubmit={submit}
        >
          <p id={`${id}-title`} className="text-body font-medium">
            {t.customDatesTitle}
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex min-w-0 flex-col gap-1.5">
              <label htmlFor={`${id}-from`} className="text-small font-medium">
                {t.from}
              </label>
              <Input
                id={`${id}-from`}
                type="date"
                value={from}
                max={to || undefined}
                aria-invalid={Boolean(error) || undefined}
                aria-describedby={error ? errorId : `${id}-hint`}
                onChange={(e) => {
                  setFrom(e.target.value);
                  setError(undefined);
                }}
              />
            </div>
            <div className="flex min-w-0 flex-col gap-1.5">
              <label htmlFor={`${id}-to`} className="text-small font-medium">
                {t.to}
              </label>
              <Input
                id={`${id}-to`}
                type="date"
                value={to}
                min={from || undefined}
                aria-invalid={Boolean(error) || undefined}
                aria-describedby={error ? errorId : `${id}-hint`}
                onChange={(e) => {
                  setTo(e.target.value);
                  setError(undefined);
                }}
              />
            </div>
          </div>
          {error ? (
            <p id={errorId} role="alert" className="text-small text-destructive">
              {error}
            </p>
          ) : (
            <p id={`${id}-hint`} className="text-small text-muted-foreground">
              {t.rangeHint}
            </p>
          )}
          <Button type="submit" size="sm" className="self-end">
            <Check aria-hidden="true" data-icon-motion="pop" />
            {t.apply}
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}
