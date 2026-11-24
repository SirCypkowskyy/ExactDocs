import { type FormEvent, useState } from "react";
import { HttpError } from "@/shared/lib/http";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";
import { DialogContent, DialogDescription, DialogRoot, DialogTitle } from "@/shared/ui/dialog";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { SelectField } from "@/shared/ui/select-field";
import { putGrant } from "../api/grants";
import { messages } from "../messages";
import {
  type CallerRole,
  explainSharingError,
  type GrantedRole,
  givableRoles,
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
  const t = useMessages(messages);
  const c = useMessages(common);
  const language = useLanguage();
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
      setSubjectError(kind === "user" ? t.share.enterUsername : t.share.enterGroup);
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
        setSubjectError(explainSharingError(error, language));
        document.getElementById("share-subject")?.focus();
      } else {
        setProblem(explainSharingError(error, language));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <DialogTitle>{t.share.title(libraryId)}</DialogTitle>
      <DialogDescription>{t.share.description}</DialogDescription>
      <div className="mt-5">
        <FormAlert id="share-alert" message={problem} />
      </div>
      <div className="flex flex-col gap-4">
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-body font-medium">{t.share.with}</legend>
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
                {k === "user" ? t.share.person : t.share.group}
              </label>
            ))}
          </div>
        </fieldset>
        <Field
          id="share-subject"
          label={kind === "user" ? t.share.username : t.share.groupName}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          hint={kind === "group" ? t.share.groupHint : undefined}
          error={subjectError}
        />
        <SelectField
          id="share-role"
          label={t.share.role}
          value={role}
          onChange={(e) => setRole(e.target.value as GrantedRole)}
          hint={t.roleHints[role]}
        >
          {givableRoles(caller).map((r) => (
            <option key={r} value={r}>
              {t.roles[r]}
            </option>
          ))}
        </SelectField>
        {caller !== "creator" && (
          <p className="text-small text-muted-foreground">{t.share.creatorOnly}</p>
        )}
      </div>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" aria-disabled={pending} onClick={() => !pending && onDone()}>
          {c.cancel}
        </Button>
        <Button type="submit" pending={pending}>
          {t.share.submit}
        </Button>
      </div>
    </form>
  );
}
