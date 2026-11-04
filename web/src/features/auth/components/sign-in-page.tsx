import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { signIn } from "../api/session-query";
import { explainError, type FormProblem } from "../model/errors";
import { safeNext, validateSignIn } from "../model/session";
import { AuthLayout } from "./auth-layout";
import { Field } from "./field";
import { focusField } from "./focus-field";
import { FORM_ALERT_ID, FormAlert, SubmitButton } from "./form-parts";

export function SignInPage({
  next,
  onSignedIn,
}: {
  next?: string | undefined;
  onSignedIn: (to: string) => void;
}) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState<FormProblem>({});

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = new FormData(event.currentTarget);
    const credentials = {
      username: String(form.get("username") ?? "").trim(),
      password: String(form.get("password") ?? ""),
    };
    const fields = validateSignIn(credentials);
    setProblem({ fields });
    if (fields.username || fields.password)
      return focusField(fields.username ? "username" : "password");

    setPending(true);
    try {
      await signIn(queryClient, credentials);
      onSignedIn(safeNext(next) ?? "/");
    } catch (error) {
      const found = explainError(error);
      setProblem(found);
      // The password is the likelier typo, and it is selected so retyping replaces it.
      if (found.message) focusField("password", { select: true });
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthLayout title="Sign in" intro="Sign in to this ExactDocs server.">
      <form onSubmit={submit} noValidate>
        <FormAlert problem={problem} />
        <div className="flex flex-col gap-5">
          <Field
            id="username"
            label="Username"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            error={problem.fields?.username}
          />
          <Field
            id="password"
            label="Password"
            type="password"
            autoComplete="current-password"
            error={problem.fields?.password}
            alertId={problem.message ? FORM_ALERT_ID : undefined}
          />
          <SubmitButton pending={pending} idle="Sign in" busy="Signing in" />
        </div>
      </form>
    </AuthLayout>
  );
}
