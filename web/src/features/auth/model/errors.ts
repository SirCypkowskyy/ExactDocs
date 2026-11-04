import { HttpError } from "@/shared/lib/http";
import type { FieldErrors } from "./session";

export interface FormProblem {
  /** Shown in the alert above the form. */
  message?: string;
  fields?: FieldErrors;
  /** The instance got its admin while this page was open. */
  alreadySetUp?: boolean;
}

/** Turn a failed request into words a person can act on. */
export function explainError(error: unknown): FormProblem {
  if (!(error instanceof HttpError)) {
    return { message: "Can't reach the server. Check your connection and try again." };
  }
  if (error.code === "invalid_credentials") {
    return { message: "That username and password don't match. Check them and try again." };
  }
  if (error.code === "already_set_up") {
    return { message: "This instance already has an admin.", alreadySetUp: true };
  }
  if (error.code === "invalid_username") return { fields: { username: error.message } };
  if (error.status === 422 && error.fields.length > 0) {
    const fields: FieldErrors = {};
    for (const f of error.fields) {
      const name = f.loc.at(-1);
      if (name === "username" || name === "password") fields[name] ??= f.msg;
    }
    if (Object.keys(fields).length > 0) return { fields };
  }
  return {
    message: `Something went wrong on the server (${error.status}). Try again in a moment.`,
  };
}
