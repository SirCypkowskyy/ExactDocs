import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Ban,
  CircleCheck,
  KeyRound,
  LogIn,
  Plus,
  ShieldCheck,
  UserCheck,
  UserRound,
  Users,
  UserX,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { cn } from "@/shared/lib/utils";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { ConfirmDialog } from "@/shared/ui/confirm-dialog";
import { Person, RelativeTime } from "@/shared/ui/data-table/cells";
import { DataTable } from "@/shared/ui/data-table/data-table";
import { DataTablePagination } from "@/shared/ui/data-table/pagination";
import { type RowAction, restoreRowFocus } from "@/shared/ui/data-table/row-actions";
import { pageQueryOptions } from "@/shared/ui/data-table/server-pages";
import { pageOf } from "@/shared/ui/data-table/table-search";
import { DataTableToolbar } from "@/shared/ui/data-table/toolbar";
import { type TableFilter, useDataTable } from "@/shared/ui/data-table/use-data-table";
import { FormAlert } from "@/shared/ui/form-alert";
import { Page, PageHeader } from "@/shared/ui/page";
import { setUserDisabled, usersKey, usersSource } from "../api/users-query";
import { messages } from "../messages";
import { parseUsersView, USER_ROLES, USER_STATUSES, USERS_TABLE } from "../model/list-view";
import { explainUserError, type Role, type User } from "../model/user";
import { CreateUserDialog } from "./create-user-dialog";
import { GroupChips } from "./group-chips";
import { ResetPasswordDialog } from "./reset-password-dialog";

/*
 * The operator's users page (blocks-map §2.3, Users): every account in DataTable v2, numbered
 * pages sorted and filtered by the server, the view in the URL; create, reset a password, disable
 * (behind a confirmation) or enable, from the row's menu or its context menu.
 */

type UsersMessages = (typeof messages)["en"];

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

function SignInCell({ user }: { user: User }) {
  const t = useMessages(messages).row;
  const Icon = user.provider ? LogIn : KeyRound;
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-muted-foreground">
      <Icon aria-hidden="true" className="size-3.5 flex-none" />
      <span className="truncate">{user.provider ?? t.password}</span>
    </span>
  );
}

// Built once per language and operator: a cell is rendered as a component, so a new function
// would remount it.
const columnsOf = (m: UsersMessages, me: string): ColumnDef<User>[] => [
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
      return (
        <Badge>
          <Icon aria-hidden="true" className="size-3" />
          {roleName(m, row.original.role)}
        </Badge>
      );
    },
  },
  {
    id: "sign_in",
    header: m.list.signIn,
    enableSorting: false,
    meta: { label: m.list.signIn, className: "max-md:hidden" },
    cell: ({ row }) => <SignInCell user={row.original} />,
  },
  {
    id: "groups",
    header: m.list.groups,
    enableSorting: false,
    meta: { label: m.list.groups, className: "max-lg:hidden" },
    cell: ({ row }) => (
      <GroupChips name={row.original.username} groups={row.original.groups ?? []} />
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
    meta: { priority: 3 },
    cell: ({ row }) => <RelativeTime iso={row.original.created_at} />,
  },
];

const filtersOf = (m: UsersMessages): TableFilter[] => [
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
];

/** The operator's users page: list, create, disable or enable, and reset a password. */
export function UsersPage({ currentUserId }: { currentUserId: string }) {
  const view = parseUsersView(useSearch({ strict: false }) as Record<string, unknown>);
  const language = useLanguage();
  const m = useMessages(messages);
  const t = m.page;
  const heading = usePageTitle(t.title);
  const queryClient = useQueryClient();
  const columns = useMemo(() => columnsOf(m, currentUserId), [m, currentUserId]);
  const filters = useMemo(() => filtersOf(m), [m]);
  const source = usersSource(view);
  const model = useDataTable({
    config: USERS_TABLE,
    search: view,
    columns,
    getRowId: (user) => user.id,
    filters,
    source,
  });
  // The failure of the shown page, to say why in words (a non-operator is refused, 403).
  const { page, size } = pageOf(view, USERS_TABLE);
  const failure = queryClient.getQueryState(pageQueryOptions(source, page, size).queryKey)?.error;
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
      // A reset ends every session of the account, the operator's own included. An account of
      // an identity provider has no password to reset.
      ...(!you && !user.provider
        ? [
            {
              id: "reset",
              label: m.actions.reset,
              icon: KeyRound,
              motion: "tilt" as const,
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
        errorMessage={failure ? explainUserError(failure, language) : t.loadFailed}
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
