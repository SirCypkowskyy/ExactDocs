import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button } from "@/shared/ui/button";
import {
  ConfirmAction,
  ConfirmCancel,
  ConfirmContent,
  ConfirmDescription,
  ConfirmRoot,
  ConfirmTitle,
} from "@/shared/ui/dialog";
import { revokeToken, tokensKey, tokensQueryOptions } from "../api/tokens-query";
import { explainTokenError, isAlreadyGone, MAX_TOKENS, type Token } from "../model/token";
import { CreateTokenDialog } from "./create-token-dialog";
import { TokenList } from "./token-list";

/** API tokens: the account's list, create-once-and-copy, and confirmed revoke. */
export function TokensSection() {
  const queryClient = useQueryClient();
  const tokens = useQuery(tokensQueryOptions());
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<Token>();
  const [announcement, setAnnouncement] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const focusHeadingAfterClose = useRef(false);

  const revoke = useMutation({
    // Already revoked elsewhere counts as done: the row should go either way.
    mutationFn: (id: string) =>
      revokeToken(id).catch((error: unknown) => {
        if (!isAlreadyGone(error)) throw error;
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: tokensKey }),
    onSuccess: (_, id) => {
      const name = revoking?.id === id ? revoking.name : "Token";
      focusHeadingAfterClose.current = true;
      setRevoking(undefined);
      setAnnouncement(`${name} revoked.`);
    },
  });

  const count = tokens.data?.length ?? 0;
  const full = count >= MAX_TOKENS;

  return (
    <section aria-labelledby="tokens-heading" className="mt-12 border-t border-border pt-10">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="max-w-prose">
          <h2
            id="tokens-heading"
            ref={heading}
            tabIndex={-1}
            className="font-serif text-2xl font-semibold tracking-tight outline-none"
          >
            API tokens
          </h2>
          <p className="mt-1.5 text-muted-foreground">
            Connect an agent to ExactDocs without signing in. A token is shown once, when you create
            it.
          </p>
        </div>
        <Button
          aria-disabled={full}
          aria-describedby={full ? "token-limit" : undefined}
          className="aria-disabled:cursor-not-allowed aria-disabled:bg-primary/60 aria-disabled:hover:bg-primary/60"
          onClick={() => !full && setCreating(true)}
        >
          New token
        </Button>
      </div>
      {full && (
        <p id="token-limit" className="mt-3 text-sm text-muted-foreground">
          You have {MAX_TOKENS} of {MAX_TOKENS} tokens. Revoke one you no longer use to create
          another.
        </p>
      )}
      <p role="status" className="sr-only">
        {announcement}
      </p>

      <div className="mt-6">
        {tokens.isPending ? (
          <TokenSkeleton />
        ) : tokens.isError ? (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-md bg-destructive/10 py-1.5 pr-1.5 pl-4"
          >
            <p className="text-sm font-medium text-destructive">
              {explainTokenError(tokens.error)}
            </p>
            <Button
              variant="ghost"
              className="text-destructive hover:bg-destructive/10 max-sm:-ml-3"
              onClick={() => tokens.refetch()}
            >
              Try again
            </Button>
          </div>
        ) : tokens.data.length === 0 ? (
          <div>
            <p className="font-medium">No tokens yet.</p>
            <p className="mt-1 text-muted-foreground">
              Create one, then send it to <code className="text-sm">/mcp</code> as a bearer token:
            </p>
            <code className="mt-3 block overflow-x-auto rounded-md bg-secondary px-3 py-2.5 text-sm whitespace-nowrap">
              Authorization: Bearer exd_...
            </code>
          </div>
        ) : (
          <TokenList tokens={tokens.data} onRevoke={setRevoking} />
        )}
      </div>

      <CreateTokenDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(name) => setAnnouncement(`Token ${name} created.`)}
      />

      <ConfirmRoot
        open={revoking !== undefined}
        onOpenChange={(open) => {
          if (!open) {
            setRevoking(undefined);
            revoke.reset();
          }
        }}
      >
        <ConfirmContent
          onCloseAutoFocus={(event) => {
            // The revoked row is gone, so there is nothing to return to: land on the section.
            if (focusHeadingAfterClose.current) {
              event.preventDefault();
              focusHeadingAfterClose.current = false;
              heading.current?.focus();
            }
          }}
        >
          <ConfirmTitle>Revoke “{revoking?.name}”?</ConfirmTitle>
          <ConfirmDescription>
            Anything using{" "}
            {revoking ? <code className="text-foreground">{revoking.prefix}…</code> : "it"} stops
            working at once. This can't be undone.
          </ConfirmDescription>
          <p
            role="alert"
            className="empty:hidden mt-4 rounded-md bg-destructive/10 px-3 py-2.5 text-sm font-medium text-destructive"
          >
            {revoke.isError && explainTokenError(revoke.error)}
          </p>
          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <ConfirmCancel asChild>
              <Button variant="ghost">Cancel</Button>
            </ConfirmCancel>
            <ConfirmAction asChild>
              <Button
                className="bg-destructive hover:bg-destructive/90"
                aria-disabled={revoke.isPending}
                onClick={(event) => {
                  event.preventDefault(); // stay open until the server answers
                  if (revoking && !revoke.isPending) revoke.mutate(revoking.id);
                }}
              >
                {revoke.isPending ? "Revoking" : "Revoke"}
              </Button>
            </ConfirmAction>
          </div>
        </ConfirmContent>
      </ConfirmRoot>
    </section>
  );
}

function TokenSkeleton() {
  return (
    <div aria-busy="true">
      <span className="sr-only">Loading tokens</span>
      <div aria-hidden="true" className="divide-y divide-border border-y border-border">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center justify-between gap-4 py-4">
            <div>
              <div className="flex h-6 items-center">
                <div className="h-3.5 w-32 rounded bg-secondary motion-safe:animate-pulse" />
              </div>
              <div className="mt-1 flex h-5 items-center">
                <div className="h-3 w-56 max-w-full rounded bg-secondary motion-safe:animate-pulse" />
              </div>
            </div>
            <div className="h-9 w-[4.5rem] rounded bg-secondary motion-safe:animate-pulse" />
          </div>
        ))}
      </div>
    </div>
  );
}
