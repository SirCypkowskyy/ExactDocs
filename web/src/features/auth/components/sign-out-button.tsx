import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/shared/ui/button";
import { signOut } from "../api/session-query";

export function SignOutButton({ onSignedOut }: { onSignedOut: () => void }) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  async function run() {
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
    <>
      <Button variant="ghost" onClick={run} disabled={pending} aria-busy={pending}>
        {pending ? "Signing out" : "Sign out"}
      </Button>
      <span role="alert" className="text-sm font-medium text-destructive">
        {failed && "Couldn't sign out. Try again."}
      </span>
    </>
  );
}
