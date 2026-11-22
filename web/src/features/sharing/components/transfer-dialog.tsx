import { type FormEvent, useState } from "react";
import { HttpError } from "@/shared/lib/http";
import { Button } from "@/shared/ui/button";
import { DialogContent, DialogDescription, DialogRoot, DialogTitle } from "@/shared/ui/dialog";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { transferLibrary } from "../api/grants";
import { explainSharingError } from "../model/grant";

interface Props {
  owner: string;
  repo: string;
  libraryId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onTransferred: (username: string) => void;
}

/** Hand the library over to another user. Only its creator (or an operator) sees this. */
export function TransferDialog({ open, onOpenChange, ...props }: Props) {
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
  onTransferred,
  onDone,
}: Omit<Props, "open" | "onOpenChange"> & { onDone: () => void }) {
  const [fieldError, setFieldError] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const username = String(
      new FormData(event.currentTarget).get("transfer-username") ?? "",
    ).trim();
    setProblem(undefined);
    if (!username) {
      setFieldError("Enter the username of the new creator.");
      document.getElementById("transfer-username")?.focus();
      return;
    }
    setFieldError(undefined);
    setPending(true);
    try {
      await transferLibrary(owner, repo, username);
      onTransferred(username);
      onDone();
    } catch (error) {
      const onField =
        error instanceof HttpError &&
        (error.code === "unknown_account" || error.code === "invalid_grant");
      if (onField) {
        setFieldError(explainSharingError(error));
        document.getElementById("transfer-username")?.focus();
      } else {
        setProblem(explainSharingError(error));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <DialogTitle>Transfer {libraryId}</DialogTitle>
      <DialogDescription>
        The new creator owns the library: only they make or remove admins, and only they can hand it
        over again. Its creator now, if it has one, stays on as an admin.
      </DialogDescription>
      <div className="mt-5">
        <FormAlert id="transfer-alert" message={problem} />
      </div>
      <Field
        id="transfer-username"
        label="New creator's username"
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        error={fieldError}
      />
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" aria-disabled={pending} onClick={() => !pending && onDone()}>
          Cancel
        </Button>
        <Button type="submit" variant="destructive-solid" pending={pending}>
          Transfer ownership
        </Button>
      </div>
    </form>
  );
}
