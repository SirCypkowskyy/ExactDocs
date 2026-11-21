import { UI_LOCALE } from "@/shared/lib/time";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { isExpired, type Token } from "../model/token";

const date = new Intl.DateTimeFormat(UI_LOCALE, { dateStyle: "medium" });
const when = (iso: string) => date.format(new Date(iso));

export function TokenList({
  tokens,
  onRevoke,
}: {
  tokens: readonly Token[];
  onRevoke: (token: Token) => void;
}) {
  return (
    <ul aria-label="API tokens" className="divide-y divide-rule border-y border-border">
      {tokens.map((token) => {
        const expired = isExpired(token);
        return (
          <li key={token.id} className="row-in flex items-start justify-between gap-3 py-4">
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span
                  className={cn(
                    "font-medium [overflow-wrap:anywhere]",
                    expired && "text-muted-foreground",
                  )}
                >
                  {token.name}
                </span>
                <code className="font-mono text-small text-muted-foreground">{token.prefix}…</code>
              </p>
              <p className="mt-0.5 text-small text-muted-foreground [overflow-wrap:anywhere]">
                {token.library_ids == null
                  ? "All libraries you can access"
                  : token.library_ids.length === 0
                    ? "No libraries"
                    : token.library_ids.join(", ")}
              </p>
              <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-small text-muted-foreground tabular-nums">
                <span>Created {when(token.created_at)}</span>
                <span className={expired ? "font-medium text-destructive" : undefined}>
                  {token.expires_at
                    ? expired
                      ? `Expired ${when(token.expires_at)}`
                      : `Expires ${when(token.expires_at)}`
                    : "No expiry"}
                </span>
                <span>
                  {token.last_used_at ? `Last used ${when(token.last_used_at)}` : "Never used"}
                </span>
              </p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="shrink-0 text-destructive hover:bg-destructive-soft"
              aria-label={`Revoke ${token.name}`}
              onClick={() => onRevoke(token)}
            >
              Revoke
            </Button>
          </li>
        );
      })}
    </ul>
  );
}
