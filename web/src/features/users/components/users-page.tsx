import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  Ban,
  CircleCheck,
  KeyRound,
  LogIn,
  Plus,
  ScrollText,
  ShieldCheck,
  UserCheck,
  UserRound,
  Users,
  UserX,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { type Language, useLanguage, useMessages } from "@/shared/lib/i18n";
import { ruleText } from "@/shared/lib/role-rules";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { cn } from "@/shared/lib/utils";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { ConfirmDialog } from "@/shared/ui/confirm-dialog";
import { Chips, Count, Person, RelativeTime } from "@/shared/ui/data-table/cells";
import { DataTable } from "@/shared/ui/data-table/data-table";
import type { ColumnDef } from "@/shared/ui/data-table/features";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import { type RowAction, restoreRowFocus } from "@/shared/ui/data-table/row-actions";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import { type TableFilter, useDataTable } from "@/shared/ui/data-table/use-data-table";
import { FormAlert } from "@/shared/ui/form-alert";
import { Page, PageHeader } from "@/shared/ui/page";
import { roleRulesQueryOptions } from "../api/role-rules-query";
import { setUserDisabled, usersKey, usersSource } from "../api/users-query";
import { messages } from "../messages";
import {
  PASSWORD,
  parseUsersView,
  USER_ROLES,
  USER_STATUSES,
  USERS_TABLE,
} from "../model/list-view";
import { type RoleRuleList, rulesOf } from "../model/role-rule";
import { explainUserError, type Role, type User } from "../model/user";
import { rulesMessages } from "../rules-messages";
import { CreateUserDialog } from "./create-user-dialog";
import { ResetPasswordDialog } from "./reset-password-dialog";
import { UsersViews } from "./users-views";

/*
 * The operator's users page (blocks-map §2.3, Users): every account in DataTable v2, numbered
 * pages sorted and filtered by the server, the view in the URL; create, reset a password, disable
 * (behind a confirmation) or enable, from the row's menu or its context menu.
 */

type UsersMessages = (typeof messages)["en"];

/** A configured sign-in provider, as `GET /session` lists it: its name and what people call it. */
interface SignInProvider {
  name: string;
  display_name: string;
}

/** A provider's name in words, when it is configured; else its name as the account shows it. */
type ProviderNames = ReadonlyMap<string, string>;

/** A role the API sends, by its name; one this client does not know shows as sent. */
const roleName = (m: UsersMessages, role: string) => m.roles[role as Role] ?? role;

function UserCell({ user, you }: { user: User; you: boolean }) {
  const t = useMessages(messages).row;
  return (
    <span className={cn("flex min-w-0", user.disabled && "text-muted-foreground")}>
      <Person name={user.username}>{you && <Badge tone="route">{t.you}</Badge>}</Person>
    </span>
  );
}

function SignInCell({ user, names }: { user: User; names: ProviderNames }) {
  const t = useMessages(messages).row;
  const Icon = user.provider ? LogIn : KeyRound;
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-muted-foreground">
      <Icon aria-hidden="true" className="size-3.5 flex-none" />
      <span className="truncate">
        {user.provider ? (names.get(user.provider) ?? user.provider) : t.password}
      </span>
    </span>
  );
}

// Built once per language and operator: a cell is rendered as a component, so a new function
// would remount it.
const columnsOf = (
  m: UsersMessages,
  me: string,
  names: ProviderNames,
  rules: RoleRuleList | undefined,
  language: Language,
): ColumnDef<User>[] => [
  {
    accessorKey: "username",
    header: m.list.columns.account,
    enableHiding: false,
    meta: { priority: 1, skeleton: "avatar" },
    cell: ({ row }) => <UserCell user={row.original} you={row.original.id === me} />,
  },
  {
    accessorKey: "role",
    header: m.list.columns.role,
    meta: { priority: 2, skeleton: "pill" },
    cell: ({ row }) => {
      const Icon = row.original.role === "admin" ? ShieldCheck : UserRound;
      // An admin through an instance_admin rule (admin_groups among them) says so.
      const fromRule =
        row.original.role === "admin" &&
        rulesOf(row.original.rules ?? [], rules).some((r) => r.grant === "instance_admin");
      return (
        <span className="inline-flex flex-wrap items-center gap-1.5">
          <Badge>
            <Icon aria-hidden="true" className="size-3" />
            {roleName(m, row.original.role)}
          </Badge>
          {fromRule && (
            <span className="text-small text-muted-foreground">
              {rulesMessages[language].origin.fromRule}
            </span>
          )}
        </span>
      );
    },
  },
  {
    id: "sign_in",
    header: m.list.signIn,
    enableSorting: false,
    meta: { label: m.list.signIn, className: "max-md:hidden" },
    cell: ({ row }) => <SignInCell user={row.original} names={names} />,
  },
  {
    id: "groups",
    header: m.list.groups,
    enableSorting: false,
    meta: { label: m.list.groups, className: "max-lg:hidden" },
    cell: ({ row }) => (
      <Chips
        items={row.original.groups ?? []}
        more={(n) => m.list.moreGroups(n, row.original.username)}
        title={m.list.allGroups(row.original.username)}
      />
    ),
  },
  {
    id: "rules",
    header: rulesMessages[language].origin.rules,
    enableSorting: false,
    meta: { label: rulesMessages[language].origin.rules, className: "max-lg:hidden" },
    cell: ({ row }) => (
      <Chips
        items={rulesOf(row.original.rules ?? [], rules).map((r) => ruleText(r, language))}
        more={(n) => rulesMessages[language].origin.more(n, row.original.username)}
        title={rulesMessages[language].origin.all(row.original.username)}
        look="pill"
      />
    ),
  },
  {
    id: "status",
    header: m.list.columns.status,
    enableSorting: false,
    meta: { priority: 2, skeleton: "pill", label: m.list.columns.status },
    cell: ({ row }) =>
      row.original.disabled ? (
        <Badge>
          <Ban aria-hidden="true" className="size-3" />
          {m.row.disabled}
        </Badge>
      ) : (
        <span className="text-muted-foreground">{m.row.active}</span>
      ),
  },
  {
    accessorKey: "created_at",
    header: m.list.columns.created,
    sortDescFirst: true,
    meta: { priority: 3, className: "max-xl:hidden" },
    cell: ({ row }) => <RelativeTime iso={row.original.created_at} />,
  },
  {
    // Kept to the hour by the server: the tooltip's exact time says so.
    accessorKey: "last_active_at",
    header: m.list.columns.lastActive,
    sortDescFirst: true,
    meta: { priority: 3, label: m.list.columns.lastActive },
    cell: ({ row }) => <RelativeTime iso={row.original.last_active_at} empty={m.list.never} />,
  },
  {
    accessorKey: "token_count",
    header: m.list.columns.tokens,
    sortDescFirst: true,
    meta: { align: "end", skeleton: "number", className: "max-md:hidden" },
    cell: ({ row }) => (
      <Count value={row.original.token_count} muted={row.original.token_count === 0} />
    ),
  },
];

/**
 * The sign-in filter's choices: a password, each configured provider, and any other the URL names
 * (an account can come from a provider that is no longer configured).
 */
function providerOptions(m: UsersMessages, names: ProviderNames, picked: readonly string[]) {
  const others = picked.filter((p) => p !== PASSWORD && !names.has(p));
  return [
    { value: PASSWORD, label: m.row.password, icon: KeyRound },
    ...[...names].map(([name, label]) => ({ value: name, label, icon: LogIn })),
    ...others.map((name) => ({ value: name, label: name, icon: LogIn })),
  ];
}

const filtersOf = (
  m: UsersMessages,
  names: ProviderNames,
  picked: readonly string[],
): TableFilter[] => [
  {
    id: "role",
    title: m.list.role,
    options: USER_ROLES.map((r) => ({
      value: r,
      label: m.roles[r],
      icon: r === "admin" ? ShieldCheck : UserRound,
    })),
  },
  {
    id: "status",
    title: m.list.status,
    options: USER_STATUSES.map((s) => ({
      value: s,
      label: m.list[s],
      icon: s === "active" ? CircleCheck : Ban,
    })),
  },
  { id: "provider", title: m.list.signIn, options: providerOptions(m, names, picked) },
];

const NO_PROVIDERS: readonly SignInProvider[] = [];

/**
 * The operator's users page: list, create, disable or enable, and reset a password. `providers`
 * are the configured sign-in providers (from `GET /session`): the sign-in filter offers them.
 */
export function UsersPage({
  currentUserId,
  providers = NO_PROVIDERS,
}: {
  currentUserId: string;
  providers?: readonly SignInProvider[] | undefined;
}) {
  const view = parseUsersView(useSearch({ strict: false }) as Record<string, unknown>);
  const language = useLanguage();
  const m = useMessages(messages);
  const t = m.page;
  const heading = usePageTitle(t.title);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const names: ProviderNames = useMemo(
    () => new Map(providers.map((p) => [p.name, p.display_name])),
    [providers],
  );
  const pickedKey = (view.provider ?? []).join(",");
  // The rules each account matches come as IDs; their words come from the rules list.
  const rules = useQuery(roleRulesQueryOptions()).data;
  const columns = useMemo(
    () => columnsOf(m, currentUserId, names, rules, language),
    [m, currentUserId, names, rules, language],
  );
  const filters = useMemo(
    () => filtersOf(m, names, pickedKey ? pickedKey.split(",") : []),
    [m, names, pickedKey],
  );
  const source = usersSource(view);
  const model = useDataTable({
    config: USERS_TABLE,
    search: view,
    columns,
    getRowId: (user) => user.id,
    filters,
    source,
  });
  const [creating, setCreating] = useState(false);
  const [disabling, setDisabling] = useState<User>();
  const [resetting, setResetting] = useState<User>();
  const [announcement, setAnnouncement] = useState("");

  const toggle = useMutation({
    mutationFn: ({ user, disabled }: { user: User; disabled: boolean }) =>
      setUserDisabled(user.id, disabled),
    onSettled: () => queryClient.invalidateQueries({ queryKey: usersKey }),
    onSuccess: (user) => {
      setDisabling(undefined);
      setAnnouncement(user.disabled ? t.disabled(user.username) : t.enabled(user.username));
      toast.success(user.disabled ? t.disabledToast(user.username) : t.enabledToast(user.username));
    },
    onError: (error, { user, disabled }) => {
      // The disable dialog shows its own error; an enable has no dialog, so it speaks here.
      if (!disabled) toast.error(t.enableFailed(user.username, explainUserError(error, language)));
    },
  });

  const actions = (user: User): RowAction<User>[] => {
    const you = user.id === currentUserId;
    return [
      // Where the account shows up elsewhere: its tokens, and the access changes it made.
      {
        id: "tokens",
        label: m.actions.tokens,
        icon: KeyRound,
        motion: "tilt",
        onSelect: () => void navigate({ to: "/users/tokens", search: { owner: user.id } }),
      },
      {
        id: "access-log",
        label: m.actions.accessLog,
        icon: ScrollText,
        motion: "tilt",
        onSelect: () => void navigate({ to: "/access-log", search: { actor: user.username } }),
      },
      // A reset ends every session of the account, the operator's own included. An account of
      // an identity provider has no password to reset.
      ...(!you && !user.provider
        ? [
            {
              id: "reset",
              label: m.actions.reset,
              icon: KeyRound,
              motion: "tilt" as const,
              group: true,
              onSelect: () => setResetting(user),
            },
          ]
        : []),
      ...(user.disabled
        ? [
            {
              id: "enable",
              label: m.actions.enable,
              icon: UserCheck,
              motion: "pop" as const,
              group: true,
              onSelect: () => {
                if (!toggle.isPending) toggle.mutate({ user, disabled: false });
              },
            },
          ]
        : you
          ? []
          : [
              {
                id: "disable",
                label: m.actions.disable,
                icon: UserX,
                motion: "warn" as const,
                destructive: true,
                group: true,
                onSelect: () => {
                  toggle.reset();
                  setDisabling(user);
                },
              },
            ]),
    ];
  };

  return (
    <Page>
      <PageHeader
        title={t.title}
        icon={<Users />}
        headingRef={heading}
        description={
          <>
            <p>
              {t.description(<code className="font-mono text-small">exactdocs user create</code>)}
            </p>
            {model.total !== undefined && (
              <p role="status" className="num mt-1">
                {t.count(model.total)}
              </p>
            )}
          </>
        }
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus aria-hidden="true" data-icon-motion="turn" />
            {t.newUser}
          </Button>
        }
      />
      <UsersViews current="accounts" />
      <p role="status" className="sr-only">
        {announcement}
      </p>
      {toggle.isError && !disabling && (
        <FormAlert id="users-alert" message={explainUserError(toggle.error, language)} />
      )}
      <DataTableToolbar
        model={model}
        search={{ label: m.list.find, placeholder: m.list.usernamePlaceholder }}
      />
      <DataTable
        model={model}
        label={m.list.label}
        rowActions={actions}
        rowLabel={(user) => user.username}
        empty={{
          icon: Users,
          title: t.emptyTitle,
          body: t.emptyBody,
          action: (
            <Button variant="outline" onClick={() => setCreating(true)}>
              <Plus aria-hidden="true" data-icon-motion="turn" />
              {t.newUser}
            </Button>
          ),
        }}
        noMatch={{ title: m.list.noMatchTitle, body: m.list.noMatch }}
        // Why the shown page failed, in words (a non-operator is refused, 403).
        errorMessage={model.error ? explainUserError(model.error, language) : t.loadFailed}
      />
      <DataTablePagination model={model} />

      <CreateUserDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(username) => {
          setAnnouncement(t.created(username));
          toast.success(t.createdToast(username), { description: t.createdHint });
        }}
      />
      <ResetPasswordDialog
        user={resetting}
        onClose={() => setResetting(undefined)}
        onReset={(user) => {
          setResetting(undefined);
          setAnnouncement(t.passwordChanged(user.username));
          toast.success(t.passwordChangedToast(user.username), {
            description: t.passwordChangedHint,
          });
        }}
      />
      <ConfirmDialog
        open={disabling !== undefined}
        onOpenChange={(open) => {
          if (!open) {
            setDisabling(undefined);
            toggle.reset();
          }
        }}
        title={t.disableTitle(disabling?.username ?? "")}
        description={t.disableDescription}
        confirmLabel={t.disable}
        icon={<UserX aria-hidden="true" data-icon-motion="warn" />}
        pending={toggle.isPending}
        error={toggle.isError && disabling ? explainUserError(toggle.error, language) : undefined}
        onConfirm={() => {
          if (disabling && !toggle.isPending) toggle.mutate({ user: disabling, disabled: true });
        }}
        onCloseAutoFocus={restoreRowFocus}
      />
    </Page>
  );
}
