import { formatNumber, useLanguage, useMessages } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover";
import { messages } from "../messages";

/** How many chips a row shows before the rest move behind "+N". */
const SHOWN = 2;

const chip = "rounded-sm bg-accent px-1.5 py-0.5 font-mono text-small text-foreground";

/**
 * An account's groups at its identity provider: the first two as mono chips, the rest behind a
 * "+N" button that opens all of them (blocks-map §2.3, Users → Groups). No groups is a dash.
 */
export function GroupChips({ name, groups }: { name: string; groups: readonly string[] }) {
  const t = useMessages(messages).list;
  const language = useLanguage();
  if (groups.length === 0) return <span className="text-muted-foreground">–</span>;
  const rest = groups.length - SHOWN;
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {groups.slice(0, SHOWN).map((group) => (
        <span key={group} className={chip}>
          {group}
        </span>
      ))}
      {rest > 0 && (
        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              aria-label={t.moreGroups(rest, name)}
              className="-my-2 min-w-11 px-1.5 text-small text-muted-foreground data-[state=open]:bg-accent fine:h-6 fine:min-w-6"
            >
              +{formatNumber(rest, language)}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto max-w-72 p-3">
            <p className="mb-2 text-small text-muted-foreground">{t.allGroups(name)}</p>
            <ul className="flex flex-wrap gap-1.5">
              {groups.map((group) => (
                <li key={group} className={chip}>
                  {group}
                </li>
              ))}
            </ul>
          </PopoverContent>
        </Popover>
      )}
    </span>
  );
}
