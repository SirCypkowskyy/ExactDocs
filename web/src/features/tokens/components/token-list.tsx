import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { isExpired, type Token } from "../model/token";

const date = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const when = (iso: string) => date.format(new Date(iso));

export function TokenList({
  tokens,
  onRevoke,
}: {
  tokens: readonly Token[];
  onRevoke: (token: Token) => void;
}) {
  return (
    <ul aria-label="API tokens" className="divide-y divide-border border-y border-border">
      {tokens.map((token) => {
        const expired = isExpired(token);
        return (
          <li key={token.id} className="fade-in flex items-center justify-between gap-4 py-4">
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-medium break-words">{token.name}</span>
                {expired && <Badge variant="outline">Expired</Badge>}
                <code className="text-sm text-muted-foreground">{token.prefix}…</code>
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {token.expires_at
                  ? `${expired ? "Expired" : "Expires"} ${when(token.expires_at)}`
                  : "No expiry"}
                {" · "}
                {token.last_used_at ? `Last used ${when(token.last_used_at)}` : "Never used"}
              </p>
            </div>
            <Button
              variant="ghost"
              className="shrink-0 text-destructive"
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
