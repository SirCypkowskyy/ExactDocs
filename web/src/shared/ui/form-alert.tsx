import { Info } from "lucide-react";

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
 * text when it arrives; it eases open instead of pushing the form down in one jump.
 */
export function FormAlert({ id, message, link, tone = "error" }: FormAlertProps) {
  const open = Boolean(message);
  return (
    <div
      id={id}
      role="alert"
      className={`grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}
    >
      <div className="overflow-hidden">
        {open && (
          <p
            className={`mb-5 flex items-start gap-2 rounded-md px-3 py-2.5 text-sm font-medium ${tone === "info" ? "bg-accent text-foreground" : "bg-destructive/10 text-destructive"}`}
          >
            {tone === "info" ? (
              <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-mark" />
            ) : null}
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
    </div>
  );
}
