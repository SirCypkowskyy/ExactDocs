import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Field } from "@/shared/ui/field";
import { setUp } from "../api/session-query";
import { explainError, type FormProblem } from "../model/errors";
import { MIN_PASSWORD_LENGTH, validateSetup } from "../model/session";
import { AuthLayout } from "./auth-layout";
import { focusField } from "./focus-field";
import { FormAlert, SubmitButton } from "./form-parts";

export function SetupPage({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState<FormProblem>({});

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = new FormData(event.currentTarget);
    const values = {
      username: String(form.get("username") ?? "").trim(),
      password: String(form.get("password") ?? ""),
      confirm: String(form.get("confirm") ?? ""),
    };
    const fields = validateSetup(values);
    setProblem({ fields });
    const first = (["username", "password", "confirm"] as const).find((k) => fields[k]);
    if (first) return focusField(first);

    setPending(true);
    try {
      await setUp(queryClient, { username: values.username, password: values.password });
      onDone();
    } catch (error) {
      const found = explainError(error);
      setProblem(found);
      if (found.fields?.username) focusField("username");
      else if (found.fields?.password) focusField("password");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthLayout
      title="Create the admin account"
      intro="First run. This account becomes the admin of this server."
    >
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
            autoComplete="new-password"
            hint={`At least ${MIN_PASSWORD_LENGTH} characters. A short phrase of unrelated words works well.`}
            error={problem.fields?.password}
          />
          <Field
            id="confirm"
            label="Repeat the password"
            type="password"
            autoComplete="new-password"
            error={problem.fields?.confirm}
          />
          <SubmitButton
            pending={pending}
            idle="Create account and sign in"
            busy="Creating account"
          />
        </div>
      </form>
    </AuthLayout>
  );
}
