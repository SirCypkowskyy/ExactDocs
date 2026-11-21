import { Link } from "@tanstack/react-router";
import { LibraryBig } from "lucide-react";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { buttonVariants } from "@/shared/ui/button";
import { StatusScreen } from "@/shared/ui/status-screen";

/** The address names a library this instance does not have (or the caller may not see). */
export function LibraryNotFound({ owner, repo }: { owner: string; repo: string }) {
  const heading = usePageTitle("Library not found");
  return (
    <StatusScreen
      icon={<LibraryBig aria-hidden="true" />}
      title="Library not found"
      headingRef={heading}
      actions={
        <Link to="/" className={buttonVariants()}>
          All libraries
        </Link>
      }
    >
      ExactDocs has no library{" "}
      <code className="font-mono text-foreground">
        /{owner}/{repo}
      </code>
      . Check the address, or pick one from the list.
    </StatusScreen>
  );
}
