import { Button } from "@/shared/ui/button";

/** Form-level error. `role="alert"` makes screen readers read it the moment it appears. */
export function FormAlert({ children }: { children?: React.ReactNode }) {
  if (!children) return null;
  return (
    <div
      role="alert"
      className="fade-in rounded-md bg-destructive/10 px-3 py-2.5 text-sm font-medium text-destructive"
    >
      {children}
    </div>
  );
}

export function SubmitButton({
  pending,
  idle,
  busy,
}: {
  pending: boolean;
  idle: string;
  busy: string;
}) {
  return (
    <Button type="submit" disabled={pending} aria-busy={pending} className="mt-2 w-full">
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
