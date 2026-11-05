import { HttpError } from "@/shared/lib/http";
import type { FieldErrors } from "./session";

export interface FormProblem {
  /** Shown in the alert above the form. */
  message?: string;
  fields?: FieldErrors;
  /** A way out of the problem: a plain link after the message. */
  link?: { href: "/sign-in" | "/setup"; label: string };
}

/** Setup succeeded but the sign-in that follows it did not: the admin exists, a retry would 409. */
export class AdminCreated extends Error {
  constructor() {
    super("admin created, sign-in failed");
    this.name = "AdminCreated";
  }
}

/** Turn a failed request into words a person can act on. */
export function explainError(error: unknown): FormProblem {
  if (error instanceof AdminCreated) {
    return {
      message: "The admin account was created, but signing in failed.",
      link: { href: "/sign-in", label: "Sign in" },
    };
  }
  if (!(error instanceof HttpError)) {
    return { message: "Can't reach the server. Check your connection and try again." };
  }
  if (error.code === "invalid_credentials") {
    return { message: "That username and password don't match." };
  }
  if (error.code === "rate_limited") {
    const wait = error.retryAfter;
    const when =
      wait === undefined
        ? "Wait a little, then try again."
        : `Try again in ${wait} ${wait === 1 ? "second" : "seconds"}.`;
    return { message: `Too many failed sign-ins. ${when}` };
  }
  if (error.code === "already_set_up") {
    return {
      message: "This server already has an admin.",
      link: { href: "/sign-in", label: "Sign in instead" },
    };
  }
  if (error.code === "setup_required") {
    return {
      message: "This server has no admin yet.",
      link: { href: "/setup", label: "Set it up" },
    };
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
