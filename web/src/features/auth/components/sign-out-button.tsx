import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { Button, buttonVariants } from "@/shared/ui/button";
import { signOut } from "../api/session-query";
import { useSession } from "../hooks/use-session";
import { messages } from "../messages";

export function SignOutButton({ onSignedOut }: { onSignedOut: () => void }) {
  const queryClient = useQueryClient();
  const session = useSession();
  const t = useMessages(messages);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  // Cloudflare Access signs this browser in on every request: ending only the ExactDocs session
  // would sign it straight back in. Access's own logout ends both.
  if (session?.source === "cloudflare_access" && session.sign_out_url) {
    return (
      <a
        href={session.sign_out_url}
        className={buttonVariants({ variant: "ghost" })}
        title={t.signOut.accessHint}
      >
        <LogOut aria-hidden="true" data-icon-motion="forward" />
        {t.signOut.action}
      </a>
    );
  }

  async function run() {
    if (pending) return;
    setPending(true);
    setFailed(false);
    try {
      await signOut(queryClient);
      onSignedOut();
    } catch {
      setFailed(true);
      setPending(false);
    }
  }

  return (
    <div className="relative">
      <Button
        variant="ghost"
        onClick={run}
        aria-disabled={pending}
        aria-busy={pending}
        aria-describedby={failed ? "sign-out-error" : undefined}
      >
        <LogOut aria-hidden="true" data-icon-motion="forward" />
        {pending ? t.signOut.pending : t.signOut.action}
      </Button>
      {/* Hangs below the button so a failure never moves the layout. From sm up the button sits at
          the header's right edge, so the message opens leftwards; on a phone it sits at the left of
          the Account page, so it opens rightwards. */}
      <p
        id="sign-out-error"
        role="alert"
        className="absolute top-full left-0 z-10 sm:right-0 sm:left-auto mt-1 whitespace-nowrap rounded-md bg-card px-3 py-1.5 text-body font-medium text-destructive shadow-float empty:hidden"
      >
        {failed && t.signOut.failed}
      </p>
    </div>
  );
}
