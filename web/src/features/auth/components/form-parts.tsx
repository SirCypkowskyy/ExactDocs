import type { ReactNode } from "react";
import { Button } from "@/shared/ui/button";
import type { FormProblem } from "../model/errors";

export const FORM_ALERT_ID = "form-alert";

/**
 * Form-level error. The `role="alert"` region is always mounted, so screen readers announce the
 * text when it arrives; it eases open instead of pushing the form down in one jump.
 */
export function FormAlert({ problem }: { problem: FormProblem }) {
  const open = Boolean(problem.message);
  return (
    <div
      id={FORM_ALERT_ID}
      role="alert"
      className={`grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}
    >
      <div className="overflow-hidden">
        {open && (
          <p className="mb-5 rounded-md bg-destructive/10 px-3 py-2.5 text-sm font-medium text-destructive">
            {problem.message}
            {problem.link && (
              <>
                {" "}
                <a href={problem.link.href} className="underline underline-offset-2">
                  {problem.link.label}
                </a>
              </>
            )}
          </p>
        )}
      </div>
    </div>
  );
}

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
