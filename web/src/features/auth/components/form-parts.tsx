import type { ReactNode } from "react";
import { Button } from "@/shared/ui/button";

export const FORM_ALERT_ID = "form-alert";

/** `aria-disabled` while busy keeps focus on the button; the form handler ignores repeat submits. */
export function SubmitButton({
  pending,
  idle,
  busy,
  icon,
}: {
  pending: boolean;
  idle: string;
  busy: string;
  /** A leading icon, shown while idle (the button shows its spinner while busy). */
  icon?: ReactNode;
}): ReactNode {
  return (
    <Button type="submit" pending={pending} className="mt-1 w-full">
      {!pending && icon}
      {pending ? busy : idle}
    </Button>
  );
}
