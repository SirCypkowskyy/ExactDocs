import { useNavigate } from "@tanstack/react-router";
import { Copy, LibraryBig } from "lucide-react";
import { useId } from "react";
import { toast } from "sonner";
import { common, useMessages } from "@/shared/lib/i18n";
import { useFlash } from "@/shared/lib/use-flash";
import { cn } from "@/shared/lib/utils";
import { IconButton } from "@/shared/ui/button";
import { EmptyState } from "@/shared/ui/page";
import { codeWell } from "@/shared/ui/recipes";
import { SelectField } from "@/shared/ui/select-field";
import { listMessages } from "../messages/list";
import type { ListView } from "../model/list-view";
import { AddLibraryLink } from "./add-library-link";

/*
 * Around the libraries table: the sort picker phones get instead of headers, and the first-run
 * screen of an instance with no library yet.
 */

const SORTS = [
  "title",
  "-title",
  "-last_imported_at",
  "last_imported_at",
  "-version_count",
  "version_count",
  "-article_count",
  "article_count",
] as const;

/** Phones get rows as cards, without sortable headers: the order is picked here instead. */
export function PhoneSort({ view }: { view: ListView }) {
  const t = useMessages(listMessages).toolbar;
  const id = useId();
  const navigate = useNavigate();
  const names: Record<(typeof SORTS)[number], string> = {
    title: t.nameAsc,
    "-title": t.nameDesc,
    "-last_imported_at": t.recentlyImported,
    last_imported_at: t.leastRecentlyImported,
    "-version_count": t.mostVersions,
    version_count: t.fewestVersions,
    "-article_count": t.mostArticles,
    article_count: t.fewestArticles,
  };
  return (
    <div className="w-full md:hidden">
      <SelectField
        id={`${id}-sort`}
        label={t.sortBy}
        value={view.sort ?? ""}
        onChange={(e) => {
          const sort = e.target.value || undefined;
          void navigate({
            search: (prev: Record<string, unknown>) => ({ ...prev, sort, page: undefined }),
            replace: true,
            resetScroll: false,
          } as never);
        }}
      >
        <option value="">{t.sortDefault}</option>
        {SORTS.map((s) => (
          <option key={s} value={s}>
            {names[s]}
          </option>
        ))}
      </SelectField>
    </div>
  );
}

const COMMAND = "exactdocs add https://github.com/acme/payments --path docs/";

/** An instance with no library yet: what a library is, and the two ways to add one. */
export function FirstRun() {
  const t = useMessages(listMessages).firstRun;
  const c = useMessages(common);
  const [copied, flash] = useFlash(2000);
  const copy = () => {
    void navigator.clipboard?.writeText(COMMAND).then(() => {
      flash();
      toast.success(t.commandCopied);
    });
  };
  return (
    <EmptyState
      icon={<LibraryBig aria-hidden="true" />}
      title={t.title}
      action={<AddLibraryLink />}
      className="max-w-2xl"
    >
      <p>{t.intro}</p>
      <p className="mt-4">{t.commandLine}</p>
      <div className="mt-2 flex items-start gap-1">
        <pre className={cn(codeWell, "min-w-0 flex-1 whitespace-pre-wrap")}>
          <code>{COMMAND}</code>
        </pre>
        <IconButton label={copied ? c.copied : t.copyCommand} done={copied} onClick={copy}>
          <Copy aria-hidden="true" data-icon-motion="pop" />
        </IconButton>
      </div>
    </EmptyState>
  );
}
