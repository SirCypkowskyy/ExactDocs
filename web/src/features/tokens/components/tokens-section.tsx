import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/shared/ui/button";
import {
  ConfirmAction,
  ConfirmCancel,
  ConfirmContent,
  ConfirmDescription,
  ConfirmRoot,
  ConfirmTitle,
} from "@/shared/ui/dialog";
import { EmptyState } from "@/shared/ui/page";
import { Skeleton } from "@/shared/ui/skeleton";
import { revokeToken, tokensKey, tokensQueryOptions } from "../api/tokens-query";
import type { TokensView } from "../model/list-view";
import { explainTokenError, isAlreadyGone, MAX_TOKENS, type Token } from "../model/token";
import { CreateTokenDialog } from "./create-token-dialog";
import { McpConfig } from "./mcp-config";
import { TokenList } from "./token-list";

const NO_VIEW: TokensView = {};
const ignore = () => {};

/** API tokens: the account's list, create-once-and-copy, and confirmed revoke. */
export function TokensSection({
  view = NO_VIEW,
  onView = ignore,
}: {
  /** The search and sort, held in the URL by the route. */
  view?: TokensView;
  onView?: (view: TokensView) => void;
}) {
  const queryClient = useQueryClient();
  const tokens = useInfiniteQuery(tokensQueryOptions(view));
  const loaded = tokens.data?.pages.flatMap((p) => p.tokens) ?? [];
  const total = tokens.data?.pages.at(-1)?.total ?? 0;
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
      toast.success(`${name} revoked`);
    },
  });

  // A search narrows `total`, so the limit is only known without one (the server says 409 anyway).
  const full = !view.q && total >= MAX_TOKENS;

  return (
    <section aria-labelledby="tokens-heading" className="flex flex-col gap-8">
      <div>
        <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
          <div className="min-w-0 flex-1 basis-64">
            <h2
              id="tokens-heading"
              ref={heading}
              tabIndex={-1}
              className="text-section font-semibold outline-none"
            >
              API tokens
            </h2>
            <p className="mt-1 text-body text-muted-foreground">
              Connect an agent to ExactDocs without signing in. A token is shown once, when you
              create it.
            </p>
          </div>
          <Button
            aria-disabled={full}
            aria-describedby={full ? "token-limit" : undefined}
            className="aria-disabled:cursor-not-allowed aria-disabled:bg-primary/60 aria-disabled:hover:bg-primary/60"
            onClick={() => !full && setCreating(true)}
          >
            <Plus aria-hidden="true" />
            New token
          </Button>
        </div>
        {full && (
          <p id="token-limit" className="mb-3 text-body text-muted-foreground">
            You have {MAX_TOKENS} of {MAX_TOKENS} tokens. Revoke one you no longer use to create
            another.
          </p>
        )}
        <p role="status" className="sr-only">
          {announcement}
        </p>

        {tokens.isPending ? (
          <TokenSkeleton />
        ) : tokens.isError && !tokens.data ? (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-lg bg-destructive-soft py-1.5 pr-1.5 pl-4"
          >
            <p className="text-body font-medium text-destructive-ink">
              {explainTokenError(tokens.error)}
            </p>
            <Button variant="ghost" onClick={() => tokens.refetch()}>
              Try again
            </Button>
          </div>
        ) : total === 0 && !view.q ? (
          <EmptyState
            icon={<KeyRound aria-hidden="true" />}
            title="No tokens yet"
            action={
              <Button variant="outline" onClick={() => setCreating(true)}>
                Create your first token
              </Button>
            }
          >
            Create one, then give it to your agent as a bearer token. The config below shows where
            it goes.
          </EmptyState>
        ) : (
          <TokenList
            tokens={loaded}
            view={view}
            onView={onView}
            total={total}
            hasMore={tokens.hasNextPage}
            loadingMore={tokens.isFetchingNextPage}
            onLoadMore={() => void tokens.fetchNextPage()}
            onRevoke={setRevoking}
          />
        )}
      </div>

      <McpConfig />

      <CreateTokenDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(name) => {
          setAnnouncement(`Token ${name} created.`);
          toast.success(`Token ${name} created`);
        }}
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
            className="mt-4 rounded-md bg-destructive-soft px-3 py-2.5 text-body font-medium text-destructive-ink empty:hidden"
          >
            {revoke.isError && explainTokenError(revoke.error)}
          </p>
          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <ConfirmCancel asChild>
              <Button variant="ghost">Cancel</Button>
            </ConfirmCancel>
            <ConfirmAction asChild>
              <Button
                variant="destructive-solid"
                pending={revoke.isPending}
                onClick={(event) => {
                  event.preventDefault(); // stay open until the server answers
                  if (revoking && !revoke.isPending) revoke.mutate(revoking.id);
                }}
              >
                Revoke
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
      <div aria-hidden="true" className="divide-y divide-rule border-y border-border">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-start justify-between gap-3 py-4">
            <div>
              <Skeleton className="h-5 w-32" />
              <Skeleton className="mt-1.5 h-4 w-48 max-w-full" />
              <Skeleton className="mt-2 h-4 w-64 max-w-full" />
            </div>
            <Skeleton className="h-8 w-16" />
          </div>
        ))}
      </div>
    </div>
  );
}
