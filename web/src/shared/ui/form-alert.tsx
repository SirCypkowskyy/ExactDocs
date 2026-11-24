import { CircleAlert, Info } from "lucide-react";

interface FormAlertProps {
  id: string;
  message?: string | undefined;
  /** A way out of the problem: a plain link after the message. */
  link?: { href: string; label: string } | undefined;
  /** `info` is for a wait state, not a mistake: neutral ink, no red. */
  tone?: "error" | "info" | undefined;
}

/**
 * Form-level error. The `role="alert"` region is always mounted, so screen readers announce the
 * text when it arrives; it fades in (opacity and a 4 px rise, never the height).
 */
export function FormAlert({ id, message, link, tone = "error" }: FormAlertProps) {
  const open = Boolean(message);
  return (
    <div id={id} role="alert">
      {open && (
        <p
          className={`reveal mb-5 flex items-start gap-2 rounded-md px-3 py-2.5 text-body font-medium ${tone === "info" ? "bg-route-soft text-foreground" : "bg-destructive-soft text-destructive-ink"}`}
        >
          {tone === "info" ? (
            <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-route" />
          ) : (
            <CircleAlert
              aria-hidden="true"
              data-icon-motion="alert"
              className="mt-0.5 size-4 shrink-0"
            />
          )}
          <span>
            {message}
            {link && (
              <>
                {" "}
                <a href={link.href} className="underline underline-offset-2">
                  {link.label}
                </a>
              </>
            )}
          </span>
        </p>
      )}
    </div>
  );
}
