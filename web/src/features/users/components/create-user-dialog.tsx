import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Button } from "@/shared/ui/button";
import { DialogContent, DialogDescription, DialogRoot, DialogTitle } from "@/shared/ui/dialog";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { SelectField } from "@/shared/ui/select-field";
import { createUser, usersKey } from "../api/users-query";
import {
  explainUserError,
  type FieldErrors,
  MIN_PASSWORD_LENGTH,
  ROLE_LABELS,
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
  const [fields, setFields] = useState<FieldErrors>({});
  const [problem, setProblem] = useState<string>();
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
    const found = validateNewUser(values);
    setFields(found);
    setProblem(undefined);
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
      setProblem(explainUserError(error));
    } finally {
      setPending(false);
      void queryClient.invalidateQueries({ queryKey: usersKey });
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <DialogTitle>New user</DialogTitle>
      <DialogDescription>
        Choose a first password and pass it on to its owner. They sign in with it right away.
      </DialogDescription>
      <div className="mt-5">
        <FormAlert id="new-user-alert" message={problem} />
      </div>
      <div className="flex flex-col gap-4">
        <Field
          id="new-username"
          label="Username"
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          error={fields.username}
        />
        <Field
          id="new-password"
          label="Password"
          type="password"
          autoComplete="new-password"
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          error={fields.password}
        />
        <Field
          id="new-confirm"
          label="Repeat password"
          type="password"
          autoComplete="new-password"
          error={fields.confirm}
        />
        <SelectField
          id="new-role"
          label="Role"
          defaultValue="user"
          hint="An admin also manages user accounts."
        >
          {(Object.keys(ROLE_LABELS) as Role[]).map((role) => (
            <option key={role} value={role}>
              {ROLE_LABELS[role]}
            </option>
          ))}
        </SelectField>
      </div>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" aria-disabled={pending} onClick={() => !pending && onDone()}>
          Cancel
        </Button>
        <Button type="submit" pending={pending}>
          Create user
        </Button>
      </div>
    </form>
  );
}
