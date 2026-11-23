import { Link } from "@tanstack/react-router";
import { ArrowLeft, LibraryBig } from "lucide-react";
import { useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { buttonVariants } from "@/shared/ui/button";
import { StatusScreen } from "@/shared/ui/status-screen";
import { messages } from "../messages";

/** The address names a library this instance does not have (or the caller may not see). */
export function LibraryNotFound({ owner, repo }: { owner: string; repo: string }) {
  const t = useMessages(messages).notFound;
  const heading = usePageTitle(t.title);
  return (
    <StatusScreen
      icon={<LibraryBig aria-hidden="true" />}
      title={t.title}
      headingRef={heading}
      actions={
        <Link to="/" className={buttonVariants()}>
          <ArrowLeft aria-hidden="true" data-icon-motion="back" />
          {t.allLibraries}
        </Link>
      }
    >
      {t.body(
        <code className="font-mono text-foreground">
          /{owner}/{repo}
        </code>,
      )}
    </StatusScreen>
  );
}
