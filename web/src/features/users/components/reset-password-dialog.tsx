import { type FormEvent, useState } from "react";
import { Button } from "@/shared/ui/button";
import { DialogContent, DialogDescription, DialogRoot, DialogTitle } from "@/shared/ui/dialog";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { resetUserPassword } from "../api/users-query";
import {
  explainUserError,
  type FieldErrors,
  MIN_PASSWORD_LENGTH,
  type User,
  validatePassword,
} from "../model/user";

interface Props {
  user: User | undefined;
  onClose: () => void;
  onReset: (user: User) => void;
}

/** Set a new password for someone else: their sessions end and their tokens are revoked. */
export function ResetPasswordDialog({ user, onClose, onReset }: Props) {
  return (
    <DialogRoot open={user !== undefined} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {user && <Body user={user} onClose={onClose} onReset={() => onReset(user)} />}
      </DialogContent>
    </DialogRoot>
  );
}

function Body({
  user,
  onClose,
  onReset,
}: {
  user: User;
  onClose: () => void;
  onReset: () => void;
}) {
  const [fields, setFields] = useState<FieldErrors>({});
  const [problem, setProblem] = useState<string>();
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = new FormData(event.currentTarget);
    const password = String(form.get("reset-password") ?? "");
    const found = validatePassword(password, String(form.get("reset-confirm") ?? ""));
    setFields(found);
    setProblem(undefined);
    const first = (["password", "confirm"] as const).find((k) => found[k]);
    if (first) {
      document.getElementById(`reset-${first}`)?.focus();
      return;
    }
    setPending(true);
    try {
      await resetUserPassword(user.id, password);
      onReset();
    } catch (error) {
      setProblem(explainUserError(error));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <DialogTitle>Reset the password of “{user.username}”</DialogTitle>
      <DialogDescription>
        They are signed out everywhere and their API tokens stop working. Pass the new password on
        to them.
      </DialogDescription>
      <div className="mt-5">
        <FormAlert id="reset-alert" message={problem} />
      </div>
      <div className="flex flex-col gap-4">
        <Field
          id="reset-password"
          label="New password"
          type="password"
          autoComplete="new-password"
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          error={fields.password}
        />
        <Field
          id="reset-confirm"
          label="Repeat password"
          type="password"
          autoComplete="new-password"
          error={fields.confirm}
        />
      </div>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" aria-disabled={pending} onClick={() => !pending && onClose()}>
          Cancel
        </Button>
        <Button type="submit" aria-disabled={pending} aria-busy={pending}>
          {pending ? "Resetting" : "Reset password"}
        </Button>
      </div>
    </form>
  );
}
