import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { mediumDate } from "@/shared/lib/time";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import {
  ConfirmAction,
  ConfirmCancel,
  ConfirmContent,
  ConfirmDescription,
  ConfirmRoot,
  ConfirmTitle,
} from "@/shared/ui/dialog";
import { EmptyState, Page, PageHeader } from "@/shared/ui/page";
import { pill, pillTone } from "@/shared/ui/recipes";
import { Skeleton } from "@/shared/ui/skeleton";
import { setUserDisabled, usersKey, usersQueryOptions } from "../api/users-query";
import { messages } from "../messages";
import { isFiltered, type UsersView } from "../model/list-view";
import { explainUserError, type Role, type User } from "../model/user";
import { CreateUserDialog } from "./create-user-dialog";
import { ResetPasswordDialog } from "./reset-password-dialog";
import { columnsFor, UsersList } from "./users-list";

const NO_VIEW: UsersView = {};
const ignore = () => {};

/** The operator's users page: list, create, disable or enable, and reset a password. */
export function UsersPage({
  currentUserId,
  view = NO_VIEW,
  onView = ignore,
}: {
  currentUserId: string;
  /** The filters and sort, held in the URL by the route. */
  view?: UsersView;
  onView?: (view: UsersView) => void;
}) {
  const language = useLanguage();
  const t = useMessages(messages).page;
  const c = useMessages(common);
  const heading = usePageTitle(t.title);
  const queryClient = useQueryClient();
  const users = useInfiniteQuery(usersQueryOptions(view));
  const loaded = users.data?.pages.flatMap((p) => p.users) ?? [];
  const total = users.data?.pages.at(-1)?.total ?? 0;
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
  const toggling = toggle.isPending ? toggle.variables.user.id : undefined;

  return (
    <Page>
      <PageHeader
        title={t.title}
        headingRef={heading}
        description={t.description(
          <code className="font-mono text-small">exactdocs user create</code>,
        )}
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus aria-hidden="true" />
            {t.newUser}
          </Button>
        }
      />
      <p role="status" className="sr-only">
        {announcement}
      </p>
      {toggle.isError && !disabling && (
        <p
          role="alert"
          className="mb-6 rounded-md bg-destructive-soft px-3 py-2.5 text-body font-medium text-destructive-ink"
        >
          {explainUserError(toggle.error, language)}
        </p>
      )}

      {users.isPending ? (
        <UsersSkeleton />
      ) : users.isError && !users.data ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-lg bg-destructive-soft py-1.5 pr-1.5 pl-4"
        >
          <p className="text-body font-medium text-destructive-ink">
            {explainUserError(users.error, language)}
          </p>
          <Button variant="ghost" onClick={() => users.refetch()}>
            {c.retry}
          </Button>
        </div>
      ) : total === 0 && !isFiltered(view) ? (
        <EmptyState
          icon={<Users aria-hidden="true" />}
          title={t.emptyTitle}
          action={<Button onClick={() => setCreating(true)}>{t.newUser}</Button>}
        >
          {t.emptyBody}
        </EmptyState>
      ) : (
        <UsersList
          users={loaded}
          view={view}
          onView={onView}
          total={total}
          hasMore={users.hasNextPage}
          loadingMore={users.isFetchingNextPage}
          onLoadMore={() => void users.fetchNextPage()}
          row={(user) => (
            <UserRow
              key={user.id}
              user={user}
              you={user.id === currentUserId}
              busy={toggling === user.id}
              onReset={() => setResetting(user)}
              onEnable={() => !toggle.isPending && toggle.mutate({ user, disabled: false })}
              onDisable={() => {
                toggle.reset();
                setDisabling(user);
              }}
            />
          )}
        />
      )}

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
      <ConfirmRoot
        open={disabling !== undefined}
        onOpenChange={(open) => {
          if (!open) {
            setDisabling(undefined);
            toggle.reset();
          }
        }}
      >
        <ConfirmContent>
          <ConfirmTitle>{t.disableTitle(disabling?.username ?? "")}</ConfirmTitle>
          <ConfirmDescription>{t.disableDescription}</ConfirmDescription>
          <p
            role="alert"
            className="mt-4 rounded-md bg-destructive-soft px-3 py-2.5 text-body font-medium text-destructive-ink empty:hidden"
          >
            {toggle.isError && explainUserError(toggle.error, language)}
          </p>
          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <ConfirmCancel asChild>
              <Button variant="ghost">{c.cancel}</Button>
            </ConfirmCancel>
            <ConfirmAction asChild>
              <Button
                variant="destructive-solid"
                pending={toggle.isPending}
                onClick={(event) => {
                  event.preventDefault(); // stay open until the server answers
                  if (disabling && !toggle.isPending)
                    toggle.mutate({ user: disabling, disabled: true });
                }}
              >
                {t.disable}
              </Button>
            </ConfirmAction>
          </div>
        </ConfirmContent>
      </ConfirmRoot>
    </Page>
  );
}

function UserRow({
  user,
  you,
  busy,
  onReset,
  onEnable,
  onDisable,
}: {
  user: User;
  you: boolean;
  busy: boolean;
  onReset: () => void;
  onEnable: () => void;
  onDisable: () => void;
}) {
  const language = useLanguage();
  const m = useMessages(messages);
  const t = m.row;
  const isAdmin = user.role === "admin";
  return (
    <li className={cn("row-in flex flex-col gap-y-2 py-4", columnsFor(language))}>
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span
            className={cn(
              "font-medium [overflow-wrap:anywhere]",
              user.disabled && "text-muted-foreground line-through",
            )}
          >
            {user.username}
          </span>
          {you && <span className={cn(pill, pillTone.route)}>{t.you}</span>}
        </p>
        <p className="mt-0.5 text-small text-muted-foreground">
          {user.provider ? t.signsInWith(user.provider) : t.password}
        </p>
        {user.provider && (
          <p className="mt-1 text-small text-muted-foreground">
            {user.groups && user.groups.length > 0 ? (
              <>
                <span className="sr-only">{t.groups}</span>
                <span className="flex flex-wrap gap-1.5">
                  {user.groups.map((group) => (
                    <span
                      key={group}
                      className="rounded-sm bg-accent px-1.5 py-0.5 font-mono text-small text-foreground"
                    >
                      {group}
                    </span>
                  ))}
                </span>
              </>
            ) : (
              t.noGroups
            )}
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 md:contents">
        <span
          className={cn(pill, isAdmin ? pillTone.route : pillTone.neutral, "justify-self-start")}
        >
          {m.roles[user.role as Role] ?? user.role}
        </span>
        <span
          className={cn(
            pill,
            user.disabled ? pillTone.destructive : pillTone.positive,
            "justify-self-start",
          )}
        >
          {user.disabled ? t.disabled : t.active}
        </span>
        <span className="text-small text-muted-foreground tabular-nums">
          <span className="md:hidden">{t.created}</span>
          {mediumDate(user.created_at, language)}
        </span>
      </div>
      <div className="-ml-3 flex flex-wrap gap-1 md:ml-0 md:w-44 md:justify-end">
        {/* A reset ends every session of the account, the operator's own included.
            An account of an identity provider has no password to reset. */}
        {!you && !user.provider && (
          <Button
            variant="ghost"
            size="sm"
            aria-label={t.resetNamed(user.username)}
            onClick={onReset}
          >
            {t.reset}
          </Button>
        )}
        {user.disabled ? (
          <Button
            variant="ghost"
            size="sm"
            aria-label={t.enableNamed(user.username)}
            pending={busy}
            onClick={onEnable}
          >
            {t.enable}
          </Button>
        ) : (
          !you && (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:bg-destructive-soft"
              aria-label={t.disableNamed(user.username)}
              onClick={onDisable}
            >
              {t.disable}
            </Button>
          )
        )}
      </div>
    </li>
  );
}

function UsersSkeleton() {
  const language = useLanguage();
  const t = useMessages(messages).page;
  const columns = columnsFor(language);
  return (
    <div aria-busy="true">
      <span className="sr-only">{t.loading}</span>
      <div aria-hidden="true" className="divide-y divide-rule border-y border-border">
        {[0, 1, 2].map((i) => (
          <div key={i} className={cn("flex flex-col gap-2 py-4", columns)}>
            <div>
              <Skeleton className="h-5 w-32" />
              <Skeleton className="mt-1.5 h-4 w-20" />
            </div>
            <Skeleton className="h-5 w-14 rounded-full" />
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-8 w-44" />
          </div>
        ))}
      </div>
    </div>
  );
}
