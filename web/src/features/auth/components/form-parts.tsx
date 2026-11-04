import type { ReactNode } from "react";
import { Button } from "@/shared/ui/button";
import { FormAlert as SharedFormAlert } from "@/shared/ui/form-alert";
import type { FormProblem } from "../model/errors";

export const FORM_ALERT_ID = "form-alert";

export const FormAlert = ({ problem }: { problem: FormProblem }) => (
  <SharedFormAlert id={FORM_ALERT_ID} message={problem.message} link={problem.link} />
);

/** `aria-disabled` while busy keeps focus on the button; the form handler ignores repeat submits. */
export function SubmitButton({
  pending,
  idle,
  busy,
}: {
  pending: boolean;
  idle: string;
  busy: string;
}): ReactNode {
  return (
    <Button type="submit" aria-disabled={pending} aria-busy={pending} className="mt-2 w-full">
      {pending && (
        <span
          aria-hidden="true"
          className="spin size-4 rounded-full border-2 border-primary-foreground/40 border-t-primary-foreground"
        />
      )}
      {pending ? busy : idle}
    </Button>
  );
}
