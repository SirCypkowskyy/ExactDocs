import type { ReactNode } from "react";
import { Button } from "@/shared/ui/button";

export const FORM_ALERT_ID = "form-alert";

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
    <Button type="submit" pending={pending} className="mt-1 w-full">
      {pending ? busy : idle}
    </Button>
  );
}
