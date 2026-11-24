import { Check, Save } from "lucide-react";
import { useMessages } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";
import { sharedMessages } from "../messages/shared";

/**
 * A form's Save button and the status line beside it, which says "Saved" once what was saved is
 * what the form shows.
 */
export function SaveRow({
  label,
  pending,
  blocked,
  saved,
}: {
  label: string;
  pending: boolean;
  /** Saving now would do nothing: a request is out, or nothing changed. */
  blocked: boolean;
  saved: boolean;
}) {
  const shared = useMessages(sharedMessages);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <Button
        type="submit"
        pending={pending}
        aria-disabled={blocked}
        className="min-w-32 aria-disabled:cursor-default"
      >
        {!pending && <Save aria-hidden="true" data-icon-motion="pop" />}
        {pending ? shared.saving : label}
      </Button>
      <p role="status" className="min-h-5 text-body">
        {saved && (
          <span className="fade-in inline-flex items-center gap-1.5">
            <Check aria-hidden="true" className="size-4 text-route" />
            {shared.saved}
          </span>
        )}
      </p>
    </div>
  );
}
