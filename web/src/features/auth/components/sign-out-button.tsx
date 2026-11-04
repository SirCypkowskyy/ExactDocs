import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/shared/ui/button";
import { signOut } from "../api/session-query";

export function SignOutButton({ onSignedOut }: { onSignedOut: () => void }) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

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
        {pending ? "Signing out" : "Sign out"}
      </Button>
      {/* Hangs below the button so a failure never moves the layout. */}
      <p
        id="sign-out-error"
        role="alert"
        className="absolute top-full right-0 z-10 mt-1 whitespace-nowrap rounded-md bg-card px-3 py-1.5 text-sm font-medium text-destructive shadow-md empty:hidden"
      >
        {failed && "Couldn't sign out. Try again."}
      </p>
    </div>
  );
}
