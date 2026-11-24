import { useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { setUp } from "../api/session-query";
import { messages } from "../messages";
import { explainError, type FormProblem } from "../model/errors";
import { MIN_PASSWORD_LENGTH, validateSetup } from "../model/session";
import { AuthLayout } from "./auth-layout";
import { focusField } from "./focus-field";
import { FORM_ALERT_ID, SubmitButton } from "./form-parts";

export function SetupPage({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const t = useMessages(messages);
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
    <AuthLayout title={t.setup.title} intro={t.setup.intro}>
      <form onSubmit={submit} noValidate>
        <FormAlert id={FORM_ALERT_ID} message={problem.message} link={problem.link} />
        <div className="flex flex-col gap-5">
          <Field
            id="username"
            label={t.setup.username}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            error={problem.fields?.username}
          />
          <Field
            id="password"
            label={t.setup.password}
            type="password"
            autoComplete="new-password"
            hint={t.setup.passwordHint(MIN_PASSWORD_LENGTH)}
            error={problem.fields?.password}
          />
          <Field
            id="confirm"
            label={t.setup.confirm}
            type="password"
            autoComplete="new-password"
            error={problem.fields?.confirm}
          />
          <SubmitButton
            pending={pending}
            idle={t.setup.submit}
            busy={t.setup.busy}
            icon={<UserPlus aria-hidden="true" data-icon-motion="pop" />}
          />
        </div>
      </form>
    </AuthLayout>
  );
}
