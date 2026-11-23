import { type FormEvent, useState } from "react";
import { HttpError } from "@/shared/lib/http";
import { Button } from "@/shared/ui/button";
import { DialogContent, DialogDescription, DialogRoot, DialogTitle } from "@/shared/ui/dialog";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { SelectField } from "@/shared/ui/select-field";
import { putGrant } from "../api/grants";
import {
  type CallerRole,
  explainSharingError,
  type GrantedRole,
  givableRoles,
  ROLE_HINTS,
  ROLE_LABELS,
  type SubjectKind,
} from "../model/grant";

interface Props {
  owner: string;
  repo: string;
  libraryId: string;
  caller: CallerRole;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** After the server stored it: who, and in which role. */
  onShared: (kind: SubjectKind, subject: string, role: GrantedRole) => void;
}

/** Give a user or a group a role on the library (it replaces a role they had). */
export function ShareDialog({ open, onOpenChange, ...props }: Props) {
  return (
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <Body {...props} onDone={() => onOpenChange(false)} />
      </DialogContent>
    </DialogRoot>
  );
}

function Body({
  owner,
  repo,
  libraryId,
  caller,
  onShared,
  onDone,
}: Omit<Props, "open" | "onOpenChange"> & { onDone: () => void }) {
  const [kind, setKind] = useState<SubjectKind>("user");
  const [role, setRole] = useState<GrantedRole>("viewer");
  const [subjectError, setSubjectError] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const subject = String(new FormData(event.currentTarget).get("share-subject") ?? "").trim();
    setProblem(undefined);
    if (!subject) {
      setSubjectError(kind === "user" ? "Enter a username." : "Enter a group's name.");
      document.getElementById("share-subject")?.focus();
      return;
    }
    setSubjectError(undefined);
    setPending(true);
    try {
      await putGrant(owner, repo, { kind, subject, role });
      onShared(kind, subject, role);
      onDone();
    } catch (error) {
      if (error instanceof HttpError && error.code === "unknown_account") {
        setSubjectError(explainSharingError(error));
        document.getElementById("share-subject")?.focus();
      } else {
        setProblem(explainSharingError(error));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <DialogTitle>Share {libraryId}</DialogTitle>
      <DialogDescription>
        Give a person or an identity-provider group a role. Someone who already has one gets the new
        role instead.
      </DialogDescription>
      <div className="mt-5">
        <FormAlert id="share-alert" message={problem} />
      </div>
      <div className="flex flex-col gap-4">
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-body font-medium">Share with</legend>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {(["user", "group"] as const).map((k) => (
              <label key={k} className="inline-flex min-h-11 cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="share-kind"
                  value={k}
                  checked={kind === k}
                  onChange={() => setKind(k)}
                  className="size-4 accent-primary"
                />
                {k === "user" ? "A person" : "A group"}
              </label>
            ))}
          </div>
        </fieldset>
        <Field
          id="share-subject"
          label={kind === "user" ? "Username" : "Group"}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          hint={
            kind === "group"
              ? "As your identity provider reports it, prefix included (corp:docs). Letter case matters."
              : undefined
          }
          error={subjectError}
        />
        <SelectField
          id="share-role"
          label="Role"
          value={role}
          onChange={(e) => setRole(e.target.value as GrantedRole)}
          hint={ROLE_HINTS[role]}
        >
          {givableRoles(caller).map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}
            </option>
          ))}
        </SelectField>
        {caller !== "creator" && (
          <p className="text-small text-muted-foreground">
            Only the library's creator makes someone an admin.
          </p>
        )}
      </div>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" aria-disabled={pending} onClick={() => !pending && onDone()}>
          Cancel
        </Button>
        <Button type="submit" pending={pending}>
          Share
        </Button>
      </div>
    </form>
  );
}
