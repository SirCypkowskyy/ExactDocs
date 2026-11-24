import { ChevronRight } from "lucide-react";
import { common, useMessages } from "@/shared/lib/i18n";
import type { TagRuleDraft } from "@/shared/lib/path-selection";
import { PathFields, TagRules } from "@/shared/ui/path-selection";
import { addMessages } from "../messages/add";

interface AdvancedProps {
  open: boolean;
  onOpen: (open: boolean) => void;
  include: string;
  exclude: string;
  rules: readonly TagRuleDraft[];
  pathError: string | undefined;
  tagError: string | undefined;
  showRuleErrors: boolean;
  onInclude: (v: string) => void;
  onExclude: (v: string) => void;
  onRules: (rules: TagRuleDraft[]) => void;
}

/** The optional part of the form, closed until asked for or until it holds a mistake. */
export function AdvancedOptions(p: AdvancedProps) {
  const t = useMessages(addMessages).advanced;
  const c = useMessages(common);
  return (
    <details open={p.open} onToggle={(e) => p.onOpen(e.currentTarget.open)} className="group">
      <summary className="-ml-2 flex min-h-11 w-fit cursor-pointer list-none items-center gap-2 rounded-md px-2 text-body font-medium outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring active:bg-accent [&::-webkit-details-marker]:hidden">
        <ChevronRight
          aria-hidden="true"
          className="size-4 text-muted-foreground transition-transform duration-(--dur-fast) ease-(--ease-out) group-open:rotate-90 motion-reduce:transition-none"
        />
        {t.summary}
        <span className="font-normal text-muted-foreground">({c.optional})</span>
      </summary>
      <div className="mt-4 flex flex-col gap-6" data-rules>
        <PathFields
          include={p.include}
          exclude={p.exclude}
          error={p.pathError}
          onInclude={p.onInclude}
          onExclude={p.onExclude}
        />
        <TagRules
          rules={p.rules}
          showErrors={p.showRuleErrors}
          error={p.tagError}
          onChange={p.onRules}
        />
      </div>
    </details>
  );
}
