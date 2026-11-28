import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks, Plus, Trash2, Users } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { ruleGrant, ruleSource, ruleText } from "@/shared/lib/role-rules";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Badge } from "@/shared/ui/badge";
import { Button, IconButton } from "@/shared/ui/button";
import { ConfirmDialog } from "@/shared/ui/confirm-dialog";
import { Person } from "@/shared/ui/data-table/cells";
import { EmptyState, Page, PageHeader } from "@/shared/ui/page";
import { Skeleton } from "@/shared/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableRowHeader,
} from "@/shared/ui/table";
import { RULE_CHANGE_KEYS, removeRoleRule, roleRulesQueryOptions } from "../api/role-rules-query";
import { roleRulesHelp } from "../help";
import { messages } from "../messages";
import { editableProviders, explainRuleError, type RoleRule } from "../model/role-rule";
import { rulesMessages } from "../rules-messages";
import { AddRuleDialog } from "./add-rule-dialog";
import { UsersViews } from "./users-views";

/*
 * The users page's role rules (#577): who gets which role from a provider membership. The
 * configuration file's rules come first and are read-only; an operator adds and removes the rest.
 */
export function RoleRulesPage() {
  const m = useMessages(messages);
  const t = useMessages(rulesMessages);
  const c = useMessages(common);
  const language = useLanguage();
  const heading = usePageTitle(t.page.documentTitle);
  const queryClient = useQueryClient();
  const list = useQuery(roleRulesQueryOptions());
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<RoleRule>();
  // Once a rule is gone its row is too: focus goes to the heading instead of its button.
  const removed = useRef(false);
  const refresh = () => {
    for (const queryKey of RULE_CHANGE_KEYS) void queryClient.invalidateQueries({ queryKey });
  };
  const remove = useMutation({
    mutationFn: (rule: RoleRule) => removeRoleRule(rule.id),
    onSuccess: (_, rule) => {
      removed.current = true;
      setRemoving(undefined);
      toast.success(t.remove.removed(ruleText(rule, language)));
    },
    onSettled: refresh,
  });
  const editable = editableProviders(list.data);
  const lockedNames = (list.data?.providers ?? [])
    .filter((p) => p.configured_rules_only)
    .map((p) => p.display_name)
    .join(", ");
  const providerName = (name: string | null) =>
    name === null
      ? t.list.anyProvider
      : (list.data?.providers.find((p) => p.name === name)?.display_name ?? name);

  return (
    <Page>
      <PageHeader
        title={m.page.title}
        icon={<Users />}
        headingRef={heading}
        help={roleRulesHelp}
        description={
          <>
            <p>{t.page.description}</p>
            {list.data && (
              <p role="status" className="num mt-1">
                {t.page.count(list.data.rules.length)}
              </p>
            )}
          </>
        }
        actions={
          editable.length > 0 && (
            <Button data-tour="rules-add" onClick={() => setAdding(true)}>
              <Plus aria-hidden="true" data-icon-motion="pop" />
              {t.page.add}
            </Button>
          )
        }
      />
      <UsersViews current="rules" />
      {list.data && list.data.providers.length === 0 && (
        <p className="mb-4 text-body text-muted-foreground">{t.page.noProviders}</p>
      )}
      {lockedNames && (
        <p className="mb-4 text-body text-muted-foreground">{t.page.configuredOnly(lockedNames)}</p>
      )}
      {list.isPending ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-5 w-1/2" />
        </div>
      ) : list.isError ? (
        <EmptyState
          role="alert"
          title={explainRuleError(list.error, language)}
          action={
            <Button variant="outline" onClick={() => void list.refetch()}>
              {c.retry}
            </Button>
          }
        />
      ) : list.data.rules.length === 0 ? (
        <EmptyState icon={<ListChecks />} title={t.list.emptyTitle}>
          {t.list.emptyBody}
        </EmptyState>
      ) : (
        <Table aria-label={t.list.label} data-tour="rules-list">
          <TableHeader>
            <TableRow>
              <TableHead>{t.list.columns.source}</TableHead>
              <TableHead>{t.list.columns.grant}</TableHead>
              <TableHead className="max-md:hidden">{t.list.columns.provider}</TableHead>
              <TableHead className="max-md:hidden">{t.list.columns.by}</TableHead>
              <TableHead>
                <span className="sr-only">{t.list.columns.actions}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.data.rules.map((rule) => (
              <TableRow key={rule.id}>
                <TableRowHeader className="font-mono [overflow-wrap:anywhere]">
                  {ruleSource(rule, language)}
                </TableRowHeader>
                <TableCell>{ruleGrant(rule, language)}</TableCell>
                <TableCell className="max-md:hidden">{providerName(rule.provider)}</TableCell>
                <TableCell className="max-md:hidden">
                  {rule.configured ? (
                    <Badge title={t.list.configuredHint}>{t.list.configured}</Badge>
                  ) : (
                    rule.created_by && <Person name={rule.created_by} />
                  )}
                </TableCell>
                <TableCell className="text-end">
                  {!rule.configured && (
                    <IconButton
                      size="icon-sm"
                      variant="destructive"
                      motion="warn"
                      label={t.list.remove(ruleText(rule, language))}
                      onClick={() => setRemoving(rule)}
                    >
                      <Trash2 aria-hidden="true" />
                    </IconButton>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <AddRuleDialog
        providers={editable}
        open={adding}
        onOpenChange={setAdding}
        onAdded={(text) => toast.success(t.add.added(text))}
      />
      <ConfirmDialog
        open={removing !== undefined}
        onOpenChange={(open) => {
          if (!open) {
            remove.reset();
            setRemoving(undefined);
          }
        }}
        title={t.remove.title}
        description={removing && t.remove.description(ruleText(removing, language))}
        confirmLabel={c.remove}
        pending={remove.isPending}
        error={remove.isError ? explainRuleError(remove.error, language) : undefined}
        onConfirm={() => {
          if (removing && !remove.isPending) remove.mutate(removing);
        }}
        onCloseAutoFocus={(event) => {
          if (!removed.current) return;
          removed.current = false;
          event.preventDefault();
          heading.current?.focus();
        }}
      />
    </Page>
  );
}
