import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearch } from "@tanstack/react-router";
import { Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";
import { ConfirmDialog } from "@/shared/ui/confirm-dialog";
import { DataTable } from "@/shared/ui/data-table/data-table";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import { type RowAction, restoreRowFocus } from "@/shared/ui/data-table/row-actions";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import { useDataTable } from "@/shared/ui/data-table/use-data-table";
import { revokeToken, tokensKey, tokensQueryOptions } from "../api/tokens-query";
import { messages } from "../messages";
import { parseTokensView, TOKENS_TABLE } from "../model/list-view";
import { explainTokenError, isAlreadyGone, MAX_TOKENS, type Token } from "../model/token";
import { CreateTokenDialog } from "./create-token-dialog";
import { McpConfig } from "./mcp-config";
import { columnsOf, filtersOf } from "./token-list";

/*
 * API tokens (blocks-map §2.3 and §3): the account's tokens in DataTable v2's client mode (one
 * request, at most 50), the view in the URL; create-once-and-copy, and a confirmed revoke from the
 * row's menu or its context menu.
 */
export function TokensSection() {
  const view = parseTokensView(useSearch({ strict: false }) as Record<string, unknown>);
  const queryClient = useQueryClient();
  const language = useLanguage();
  const m = useMessages(messages);
  const t = m.section;
  const tokens = useQuery(tokensQueryOptions());
  const columns = useMemo(() => columnsOf(m), [m]);
  const filters = useMemo(() => filtersOf(m), [m]);
  const model = useDataTable({
    config: TOKENS_TABLE,
    search: view,
    columns,
    getRowId: (token) => token.id,
    filters,
    query: tokens,
  });
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
      const name = revoking?.id === id ? revoking.name : undefined;
      focusHeadingAfterClose.current = true;
      setRevoking(undefined);
      setAnnouncement(t.revoked(name));
      toast.success(t.revokedToast(name));
    },
  });

  // Every token is here (filters or not), so the limit is known exactly.
  const full = (tokens.data?.length ?? 0) >= MAX_TOKENS;
  // "No token name contains …" is only true when the search box is the only filter.
  const searchOnly = view.q && !view.libraries && !view.expires && !view.used;

  const actions = (token: Token): RowAction<Token>[] => [
    {
      id: "copy-prefix",
      label: m.actions.copyPrefix,
      icon: Copy,
      motion: "pop",
      onSelect: () => {
        void navigator.clipboard?.writeText(token.prefix).then(
          () => toast.success(m.actions.copied),
          () => {},
        );
      },
    },
    {
      id: "revoke",
      label: m.actions.revoke,
      icon: Trash2,
      motion: "warn",
      destructive: true,
      group: true,
      onSelect: () => {
        revoke.reset();
        setRevoking(token);
      },
    },
  ];

  return (
    <section aria-labelledby="tokens-heading" className="flex flex-col gap-8">
      <div>
        <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
          <div className="min-w-0 flex-1 basis-64">
            <h2
              id="tokens-heading"
              ref={heading}
              tabIndex={-1}
              className="flex items-center gap-2 text-section font-semibold outline-none"
            >
              <KeyRound aria-hidden="true" className="size-4 text-muted-foreground" />
              {t.heading}
            </h2>
            <p className="mt-1 text-body text-muted-foreground">{t.description}</p>
          </div>
          <Button
            data-tour="token-new"
            aria-disabled={full}
            aria-describedby={full ? "token-limit" : undefined}
            className="aria-disabled:cursor-not-allowed aria-disabled:bg-primary/60 aria-disabled:hover:bg-primary/60"
            onClick={() => !full && setCreating(true)}
          >
            <Plus aria-hidden="true" data-icon-motion="turn" />
            {t.newToken}
          </Button>
        </div>
        {full && (
          <p id="token-limit" className="mb-3 text-body text-muted-foreground">
            {t.limit(MAX_TOKENS)}
          </p>
        )}
        <p role="status" className="sr-only">
          {announcement}
        </p>

        <div data-tour="token-list">
          <DataTableToolbar
            model={model}
            search={{ label: m.list.find, placeholder: m.list.namePlaceholder }}
          />
          <DataTable
            model={model}
            label={m.list.label}
            rowActions={actions}
            rowLabel={(token) => token.name}
            empty={{
              icon: KeyRound,
              title: t.emptyTitle,
              body: t.emptyBody,
              action: (
                <Button variant="outline" onClick={() => setCreating(true)}>
                  <Plus aria-hidden="true" data-icon-motion="turn" />
                  {t.createFirst}
                </Button>
              ),
            }}
            noMatch={{
              title: m.list.noMatchTitle,
              body: searchOnly ? m.list.noMatch(view.q ?? "") : undefined,
            }}
            errorMessage={tokens.isError ? explainTokenError(tokens.error, language) : undefined}
          />
        </div>
        <DataTablePagination model={model} />
      </div>

      <McpConfig />

      <CreateTokenDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(name) => {
          setAnnouncement(t.created(name));
          toast.success(t.createdToast(name));
        }}
      />

      <ConfirmDialog
        open={revoking !== undefined}
        onOpenChange={(open) => {
          if (!open) {
            setRevoking(undefined);
            revoke.reset();
          }
        }}
        title={t.confirmTitle(revoking?.name ?? "")}
        description={t.confirmDescription(
          revoking ? <code className="text-foreground">{revoking.prefix}…</code> : undefined,
        )}
        confirmLabel={t.revoke}
        pending={revoke.isPending}
        error={revoke.isError ? explainTokenError(revoke.error, language) : undefined}
        onConfirm={() => {
          if (revoking && !revoke.isPending) revoke.mutate(revoking.id);
        }}
        onCloseAutoFocus={(event) => {
          // The revoked row is gone, so there is nothing to return to: land on the section.
          if (focusHeadingAfterClose.current) {
            event.preventDefault();
            focusHeadingAfterClose.current = false;
            heading.current?.focus();
          } else {
            restoreRowFocus(event);
          }
        }}
      />
    </section>
  );
}
