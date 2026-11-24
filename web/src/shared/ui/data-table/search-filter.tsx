import { Search } from "lucide-react";
import { useEffect, useEffectEvent, useState } from "react";
import { cn } from "@/shared/lib/utils";
import { Input } from "../input";

/**
 * A text filter that waits until typing pauses before it changes the view (and asks the server).
 * `value` is the filter in the view: when it changes elsewhere (Clear filters), the box follows.
 * `icon` puts a search mark at the start of the field (DataTable v2's global filter).
 */
export function SearchFilter({
  id,
  label,
  placeholder,
  value,
  onCommit,
  icon = false,
  className,
}: {
  id: string;
  label: string;
  placeholder?: string | undefined;
  value: string | undefined;
  onCommit: (value: string | undefined) => void;
  icon?: boolean;
  className?: string;
}) {
  const [text, setText] = useState(value ?? "");
  const [seen, setSeen] = useState(value);
  if (seen !== value) {
    setSeen(value);
    if (text.trim() !== (value ?? "")) setText(value ?? "");
  }
  const commit = useEffectEvent((next: string) => {
    if ((value ?? "") !== next.trim()) onCommit(next.trim() || undefined);
  });
  useEffect(() => {
    const t = setTimeout(() => commit(text), 300);
    return () => clearTimeout(t);
  }, [text]);
  return (
    <div className={cn("flex min-w-0 flex-1 basis-60 flex-col gap-2", className)}>
      <label htmlFor={id} className="text-body font-medium">
        {label}
      </label>
      <div className="relative">
        {icon && (
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
          />
        )}
        <Input
          id={id}
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={placeholder}
          className={cn(icon && "pl-9")}
        />
      </div>
    </div>
  );
}
