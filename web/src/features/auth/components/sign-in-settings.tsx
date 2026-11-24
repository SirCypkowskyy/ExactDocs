import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Info, KeyRound } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";
import { FormAlert } from "@/shared/ui/form-alert";
import { Section } from "@/shared/ui/page";
import { changePassword, sessionQueryOptions } from "../api/session-query";
import { useSession } from "../hooks/use-session";
import { messages } from "../messages";
import {
  explainPasswordError,
  PASSWORD_FIELDS,
  type PasswordErrors,
  type PasswordField,
  signInMethodNote,
  validatePasswordChange,
  withoutPassword,
} from "../model/password";
import { MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH } from "../model/session";
import { focusField } from "./focus-field";
import { PasswordInput } from "./password-input";

/*
 * Account → Sign-in (#505, blocks-map §3): how this person signs in, one Section per subject.
 * Today: the password. Linked sign-in providers (#506) join as the next Section of this stack.
 */

const ALERT_ID = "password-alert";
const inputId = (field: PasswordField) => `password-${field}`;
const HIDDEN: Record<PasswordField, boolean> = { current: false, next: false, confirm: false };

export function SignInSettings() {
  return (
    <div className="flex flex-col gap-12">
      <PasswordSection />
      {/* #506: the "Linked sign-in providers" Section goes here. */}
    </div>
  );
}

function PasswordSection() {
  const session = useSession();
  const t = useMessages(messages).password;
  // The server refused a change because the account has no password (409): the note that
  // replaces the form takes focus, so the person is not left on a button that is gone.
  const [refused, setRefused] = useState(false);
  if (!session?.account) return null;
  return (
    <Section
      id="password"
      title={t.title}
      icon={<KeyRound />}
      description={session.account.has_password ? t.description : undefined}
    >
      {session.account.has_password ? (
        <PasswordForm onExternal={() => setRefused(true)} />
      ) : (
        <NoPasswordNote text={signInMethodNote(session)} focus={refused} />
      )}
    </Section>
  );
}

function NoPasswordNote({ text, focus }: { text: string; focus: boolean }) {
  const note = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (focus) note.current?.focus();
  }, [focus]);
  return (
    <p
      ref={note}
      tabIndex={-1}
      className="flex max-w-prose items-start gap-2 rounded-md bg-secondary px-3 py-2.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <span>{text}</span>
    </p>
  );
}

function PasswordForm({ onExternal }: { onExternal: () => void }) {
  const t = useMessages(messages).password;
  const language = useLanguage();
  const queryClient = useQueryClient();
  const form = useRef<HTMLFormElement>(null);
  const [invalid, setInvalid] = useState<PasswordErrors>({});
  // The failure itself, so its words follow the language if it changes meanwhile.
  const [failure, setFailure] = useState<{ error: unknown }>();
  const [shown, setShown] = useState(HIDDEN);
  const [changed, setChanged] = useState(false);
  const change = useMutation({
    mutationFn: changePassword,
    // Success changes nothing cached: this session stays, and so do the tokens. A 409 says the
    // account has no password after all, so the cached session learns that and the form goes.
    onError: (error) => {
      if (explainPasswordError(error).external) {
        queryClient.setQueryData(sessionQueryOptions().queryKey, withoutPassword);
      }
    },
  });

  const problem = failure ? explainPasswordError(failure.error, language) : {};
  const fields = failure ? (problem.fields ?? {}) : invalid;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (change.isPending) return;
    const data = new FormData(event.currentTarget);
    const values = {
      current: String(data.get(inputId("current")) ?? ""),
      next: String(data.get(inputId("next")) ?? ""),
      confirm: String(data.get(inputId("confirm")) ?? ""),
    };
    const found = validatePasswordChange(values, language);
    setInvalid(found);
    setFailure(undefined);
    setChanged(false);
    const first = PASSWORD_FIELDS.find((k) => found[k]);
    if (first) return focusField(inputId(first));

    change.mutate(
      { current_password: values.current, new_password: values.next },
      {
        onSuccess: () => {
          form.current?.reset();
          setShown(HIDDEN);
          setChanged(true);
          toast.success(t.toast, {
            description: t.toastHint,
            icon: <CircleCheck aria-hidden="true" data-icon-motion="draw" className="size-4" />,
          });
        },
        onError: (error) => {
          const explained = explainPasswordError(error, language);
          if (explained.external) return onExternal();
          setFailure({ error });
          const wrong = PASSWORD_FIELDS.find((k) => explained.fields?.[k]);
          if (wrong) focusField(inputId(wrong), { select: true });
        },
      },
    );
  }

  const box = (field: PasswordField) => ({
    id: inputId(field),
    label: t[field],
    showLabel: t.show[field],
    hideLabel: t.hide[field],
    error: fields[field],
    shown: shown[field],
    onShownChange: (next: boolean) => setShown((s) => ({ ...s, [field]: next })),
  });

  return (
    <form ref={form} onSubmit={submit} noValidate className="max-w-md">
      <FormAlert id={ALERT_ID} message={problem.message} link={problem.link} />
      <div className="flex flex-col gap-5">
        <PasswordInput {...box("current")} autoComplete="current-password" />
        <PasswordInput
          {...box("next")}
          autoComplete="new-password"
          hint={t.hint(MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH)}
        />
        <PasswordInput {...box("confirm")} autoComplete="new-password" />
        <div className="flex flex-col items-start gap-3">
          <Button type="submit" pending={change.isPending}>
            {!change.isPending && <KeyRound aria-hidden="true" data-icon-motion="tilt" />}
            {change.isPending ? t.busy : t.submit}
          </Button>
          <p role="status" className="text-body text-muted-foreground">
            {changed && (
              <span className="fade-in inline-flex items-start gap-2">
                <CircleCheck
                  aria-hidden="true"
                  data-icon-motion="draw"
                  className="mt-0.5 size-4 shrink-0 text-positive"
                />
                {t.changed}
              </span>
            )}
          </p>
        </div>
      </div>
    </form>
  );
}
