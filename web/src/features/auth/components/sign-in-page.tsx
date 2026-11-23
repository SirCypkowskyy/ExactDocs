import { useQueryClient } from "@tanstack/react-query";
import { LogIn } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { buttonVariants } from "@/shared/ui/button";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { externalSignInHref, signIn } from "../api/session-query";
import { messages } from "../messages";
import { explainError, explainSignInRefusal, type FormProblem } from "../model/errors";
import { type SignInProvider, safeNext, validateSignIn } from "../model/session";
import { AuthLayout } from "./auth-layout";
import { focusField } from "./focus-field";
import { FORM_ALERT_ID, SubmitButton } from "./form-parts";

export function SignInPage({
  next,
  error,
  providers = [],
  onSignedIn,
}: {
  next?: string | undefined;
  /** The code an identity provider's refused sign-in came back with (`?error=`). */
  error?: string | undefined;
  providers?: readonly SignInProvider[] | undefined;
  onSignedIn: (to: string) => void;
}) {
  const queryClient = useQueryClient();
  const t = useMessages(messages);
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState<FormProblem>(() => {
    const message = explainSignInRefusal(error);
    return message ? { message } : {};
  });

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
    <AuthLayout title={t.signIn.title} intro={t.signIn.intro}>
      <form onSubmit={submit} noValidate>
        <FormAlert id={FORM_ALERT_ID} message={problem.message} link={problem.link} />
        <div className="flex flex-col gap-4">
          <Field
            id="username"
            label={t.signIn.username}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            error={problem.fields?.username}
          />
          <Field
            id="password"
            label={t.signIn.password}
            type="password"
            autoComplete="current-password"
            error={problem.fields?.password}
            alertId={problem.message ? FORM_ALERT_ID : undefined}
          />
          <SubmitButton
            pending={pending}
            idle={t.signIn.submit}
            busy={t.signIn.busy}
            icon={<LogIn aria-hidden="true" data-icon-motion="forward" />}
          />
        </div>
      </form>
      {providers.length > 0 && (
        <section aria-labelledby="providers-heading" className="mt-6">
          <h2
            id="providers-heading"
            className="flex items-center gap-3 text-small text-muted-foreground before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border"
          >
            {t.signIn.or}
          </h2>
          <ul className="mt-4 flex flex-col gap-2">
            {providers.map((provider) => (
              <li key={provider.name}>
                <a
                  href={externalSignInHref(provider.name, safeNext(next))}
                  className={buttonVariants({ variant: "outline", className: "w-full" })}
                >
                  {t.signIn.withProvider(provider.display_name)}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </AuthLayout>
  );
}
