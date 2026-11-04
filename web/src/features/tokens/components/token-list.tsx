import { Button } from "@/shared/ui/button";
import { isExpired, type Token } from "../model/token";

const date = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const when = (iso: string) => date.format(new Date(iso));

// Name | Expires | Last used | Revoke. Below `md` the two dates stack under the name instead.
const columns = "md:grid md:grid-cols-[minmax(0,1fr)_9rem_9rem_auto] md:items-center md:gap-x-4";

export function TokenList({
  tokens,
  onRevoke,
}: {
  tokens: readonly Token[];
  onRevoke: (token: Token) => void;
}) {
  return (
    <div>
      <div
        aria-hidden="true"
        className={`hidden pb-2 text-sm text-muted-foreground ${columns} md:grid`}
      >
        <span>Name</span>
        <span>Expires</span>
        <span>Last used</span>
        <span className="-mr-3 w-[4.5rem]" />
      </div>
      <ul aria-label="API tokens" className="divide-y divide-border border-y border-border">
        {tokens.map((token) => {
          const expired = isExpired(token);
          return (
            <li
              key={token.id}
              className={`fade-in flex items-center justify-between gap-4 py-4 ${columns}`}
            >
              <div className="min-w-0 md:contents">
                <p className="flex flex-wrap items-baseline gap-x-2 md:block">
                  <span
                    className={`font-medium break-words ${expired ? "text-muted-foreground" : ""}`}
                  >
                    {token.name}
                  </span>{" "}
                  <code className="text-sm text-muted-foreground">{token.prefix}…</code>
                </p>
                <p className="mt-1 flex flex-wrap gap-x-2 text-sm text-muted-foreground tabular-nums md:contents">
                  <span className={expired ? "font-medium text-destructive" : undefined}>
                    {token.expires_at ? (
                      expired ? (
                        `Expired ${when(token.expires_at)}`
                      ) : (
                        <>
                          <span className="md:hidden">Expires </span>
                          {when(token.expires_at)}
                        </>
                      )
                    ) : (
                      "No expiry"
                    )}
                  </span>
                  <span aria-hidden="true" className="md:hidden">
                    ·
                  </span>
                  <span>
                    {token.last_used_at ? (
                      <>
                        <span className="md:hidden">Last used </span>
                        {when(token.last_used_at)}
                      </>
                    ) : (
                      <>
                        Never<span className="md:hidden"> used</span>
                      </>
                    )}
                  </span>
                </p>
              </div>
              <Button
                variant="ghost"
                className="-mr-3 shrink-0 text-destructive md:w-[4.5rem]"
                aria-label={`Revoke ${token.name}`}
                onClick={() => onRevoke(token)}
              >
                Revoke
              </Button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
