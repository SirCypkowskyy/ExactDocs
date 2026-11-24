import { type FormEvent, useState } from "react";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";
import { restoreRowFocus } from "@/shared/ui/data-table/row-actions";
import { DialogContent, DialogDescription, DialogRoot, DialogTitle } from "@/shared/ui/dialog";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { resetUserPassword } from "../api/users-query";
import { messages } from "../messages";
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
      {/* Opened from a row's menu: focus goes back to that row when it closes. */}
      <DialogContent onCloseAutoFocus={restoreRowFocus}>
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
  const language = useLanguage();
  const t = useMessages(messages).reset;
  const c = useMessages(common);
  const [fields, setFields] = useState<FieldErrors>({});
  // The failure itself, so its words follow the language if it changes meanwhile.
  const [failure, setFailure] = useState<{ error: unknown }>();
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = new FormData(event.currentTarget);
    const password = String(form.get("reset-password") ?? "");
    const found = validatePassword(password, String(form.get("reset-confirm") ?? ""), language);
    setFields(found);
    setFailure(undefined);
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
      setFailure({ error });
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <DialogTitle>{t.title(user.username)}</DialogTitle>
      <DialogDescription>{t.description}</DialogDescription>
      <div className="mt-5">
        <FormAlert
          id="reset-alert"
          message={failure && explainUserError(failure.error, language)}
        />
      </div>
      <div className="flex flex-col gap-4">
        <Field
          id="reset-password"
          label={t.password}
          type="password"
          autoComplete="new-password"
          hint={t.passwordHint(MIN_PASSWORD_LENGTH)}
          error={fields.password}
        />
        <Field
          id="reset-confirm"
          label={t.repeat}
          type="password"
          autoComplete="new-password"
          error={fields.confirm}
        />
      </div>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" aria-disabled={pending} onClick={() => !pending && onClose()}>
          {c.cancel}
        </Button>
        <Button type="submit" pending={pending}>
          {t.submit}
        </Button>
      </div>
    </form>
  );
}
