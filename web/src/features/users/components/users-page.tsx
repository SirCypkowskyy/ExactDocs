import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { Button } from "@/shared/ui/button";
import {
  ConfirmAction,
  ConfirmCancel,
  ConfirmContent,
  ConfirmDescription,
  ConfirmRoot,
  ConfirmTitle,
} from "@/shared/ui/dialog";
import { setUserDisabled, usersKey, usersQueryOptions } from "../api/users-query";
import { explainUserError, ROLE_LABELS, type Role, type User } from "../model/user";
import { CreateUserDialog } from "./create-user-dialog";
import { ResetPasswordDialog } from "./reset-password-dialog";

const date = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

/** The operator's users page: list, create, disable or enable, and reset a password. */
export function UsersPage({ currentUserId }: { currentUserId: string }) {
  const heading = usePageTitle("Users");
  const queryClient = useQueryClient();
  const users = useQuery(usersQueryOptions());
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
      setAnnouncement(
        user.disabled
          ? `${user.username} disabled. Their sessions ended and their tokens were revoked.`
          : `${user.username} enabled.`,
      );
    },
  });

  return (
    <main className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="max-w-prose">
          <h1
            ref={heading}
            tabIndex={-1}
            className="font-serif text-3xl font-semibold tracking-tight outline-none"
          >
            Users
          </h1>
          <p className="mt-1.5 text-muted-foreground">
            Local accounts on this server. Nobody can sign up: accounts are created here or with{" "}
            <code className="text-sm">exactdocs user create</code>.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>New user</Button>
      </div>
      <p role="status" className="sr-only">
        {announcement}
      </p>
      {toggle.isError && !disabling && (
        <p
          role="alert"
          className="mt-6 rounded-md bg-destructive/10 px-3 py-2.5 text-sm font-medium text-destructive"
        >
          {explainUserError(toggle.error)}
        </p>
      )}

      <div className="mt-8">
        {users.isPending ? (
          <p aria-busy="true" className="text-muted-foreground">
            Loading users
          </p>
        ) : users.isError ? (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-md bg-destructive/10 py-1.5 pr-1.5 pl-4"
          >
            <p className="text-sm font-medium text-destructive">{explainUserError(users.error)}</p>
            <Button
              variant="ghost"
              className="text-destructive hover:bg-destructive/10"
              onClick={() => users.refetch()}
            >
              Try again
            </Button>
          </div>
        ) : (
          <ul aria-label="User accounts" className="divide-y divide-border border-y border-border">
            {users.data.map((user) => {
              const you = user.id === currentUserId;
              return (
                <li
                  key={user.id}
                  className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-4"
                >
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-baseline gap-x-2">
                      <span
                        className={`font-medium break-words ${user.disabled ? "text-muted-foreground line-through" : ""}`}
                      >
                        {user.username}
                      </span>
                      {you && <span className="text-sm text-muted-foreground">(you)</span>}
                    </p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {ROLE_LABELS[user.role as Role] ?? user.role}
                      {" · "}
                      {user.disabled ? (
                        <span className="font-medium text-destructive">Disabled</span>
                      ) : (
                        "Active"
                      )}
                      {" · "}
                      Created {date.format(new Date(user.created_at))}
                    </p>
                  </div>
                  <div className="flex gap-1">
                    {/* A reset ends every session of the account, the operator's own included. */}
                    {!you && (
                      <Button
                        variant="ghost"
                        aria-label={`Reset the password of ${user.username}`}
                        onClick={() => setResetting(user)}
                      >
                        Reset password
                      </Button>
                    )}
                    {user.disabled ? (
                      <Button
                        variant="ghost"
                        aria-label={`Enable ${user.username}`}
                        aria-disabled={toggle.isPending}
                        onClick={() =>
                          !toggle.isPending && toggle.mutate({ user, disabled: false })
                        }
                      >
                        Enable
                      </Button>
                    ) : (
                      !you && (
                        <Button
                          variant="ghost"
                          className="text-destructive hover:bg-destructive/10"
                          aria-label={`Disable ${user.username}`}
                          onClick={() => {
                            toggle.reset();
                            setDisabling(user);
                          }}
                        >
                          Disable
                        </Button>
                      )
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <CreateUserDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(username) => setAnnouncement(`User ${username} created.`)}
      />
      <ResetPasswordDialog
        user={resetting}
        onClose={() => setResetting(undefined)}
        onReset={(user) => {
          setResetting(undefined);
          setAnnouncement(`Password of ${user.username} changed. They were signed out everywhere.`);
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
          <ConfirmTitle>Disable “{disabling?.username}”?</ConfirmTitle>
          <ConfirmDescription>
            They are signed out at once, their API tokens are revoked, and they can't sign in until
            you enable them again.
          </ConfirmDescription>
          <p
            role="alert"
            className="empty:hidden mt-4 rounded-md bg-destructive/10 px-3 py-2.5 text-sm font-medium text-destructive"
          >
            {toggle.isError && explainUserError(toggle.error)}
          </p>
          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <ConfirmCancel asChild>
              <Button variant="ghost">Cancel</Button>
            </ConfirmCancel>
            <ConfirmAction asChild>
              <Button
                className="bg-destructive hover:bg-destructive/90"
                aria-disabled={toggle.isPending}
                onClick={(event) => {
                  event.preventDefault(); // stay open until the server answers
                  if (disabling && !toggle.isPending)
                    toggle.mutate({ user: disabling, disabled: true });
                }}
              >
                {toggle.isPending ? "Disabling" : "Disable"}
              </Button>
            </ConfirmAction>
          </div>
        </ConfirmContent>
      </ConfirmRoot>
    </main>
  );
}
