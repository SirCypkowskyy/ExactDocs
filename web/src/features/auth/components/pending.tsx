import { useMessages } from "@/shared/lib/i18n";
import { messages } from "../messages";

/** First paint of a cold load: just the name, and only if the session check is slow enough to notice. */
export function Pending() {
  const t = useMessages(messages);
  return (
    <main className="pending-in grid min-h-dvh place-items-center">
      <p role="status" className="text-section text-muted-foreground">
        <span className="sr-only">{t.screens.loading}</span>
        ExactDocs
      </p>
    </main>
  );
}
