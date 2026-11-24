import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";
import { DialogContent, DialogDescription, DialogRoot, DialogTitle } from "@/shared/ui/dialog";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { SelectField } from "@/shared/ui/select-field";
import { createUser, usersKey } from "../api/users-query";
import { messages } from "../messages";
import {
  explainUserError,
  type FieldErrors,
  MIN_PASSWORD_LENGTH,
  ROLES,
  type Role,
  validateNewUser,
} from "../model/user";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (username: string) => void;
}

/** A new local account. The operator chooses its first password and passes it on. */
export function CreateUserDialog({ open, onOpenChange, onCreated }: Props) {
  return (
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <Body onDone={() => onOpenChange(false)} onCreated={onCreated} />
      </DialogContent>
    </DialogRoot>
  );
}

function Body({ onDone, onCreated }: { onDone: () => void; onCreated: (name: string) => void }) {
  const queryClient = useQueryClient();
  const language = useLanguage();
  const { create: t, roles } = useMessages(messages);
  const c = useMessages(common);
  const [fields, setFields] = useState<FieldErrors>({});
  // The failure itself, so its words follow the language if it changes meanwhile.
  const [failure, setFailure] = useState<{ error: unknown }>();
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = new FormData(event.currentTarget);
    const values = {
      username: String(form.get("new-username") ?? "").trim(),
      password: String(form.get("new-password") ?? ""),
      confirm: String(form.get("new-confirm") ?? ""),
      role: String(form.get("new-role") ?? "user") as Role,
    };
    const found = validateNewUser(values, language);
    setFields(found);
    setFailure(undefined);
    const first = (["username", "password", "confirm"] as const).find((k) => found[k]);
    if (first) {
      document.getElementById(`new-${first}`)?.focus();
      return;
    }
    setPending(true);
    try {
      const created = await createUser({
        username: values.username,
        password: values.password,
        role: values.role,
      });
      onCreated(created.username);
      onDone();
    } catch (error) {
      setFailure({ error });
    } finally {
      setPending(false);
      void queryClient.invalidateQueries({ queryKey: usersKey });
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <DialogTitle>{t.title}</DialogTitle>
      <DialogDescription>{t.description}</DialogDescription>
      <div className="mt-5">
        <FormAlert
          id="new-user-alert"
          message={failure && explainUserError(failure.error, language)}
        />
      </div>
      <div className="flex flex-col gap-4">
        <Field
          id="new-username"
          label={t.username}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          error={fields.username}
        />
        <Field
          id="new-password"
          label={t.password}
          type="password"
          autoComplete="new-password"
          hint={t.passwordHint(MIN_PASSWORD_LENGTH)}
          error={fields.password}
        />
        <Field
          id="new-confirm"
          label={t.repeat}
          type="password"
          autoComplete="new-password"
          error={fields.confirm}
        />
        <SelectField id="new-role" label={t.role} defaultValue="user" hint={t.roleHint}>
          {ROLES.map((role) => (
            <option key={role} value={role}>
              {roles[role]}
            </option>
          ))}
        </SelectField>
      </div>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" aria-disabled={pending} onClick={() => !pending && onDone()}>
          {c.cancel}
        </Button>
        <Button type="submit" pending={pending}>
          {t.submit}
        </Button>
      </div>
    </form>
  );
}
