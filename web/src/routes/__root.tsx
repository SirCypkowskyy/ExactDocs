import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import type { RouterContext } from "@/app/router";
import { useSession } from "@/features/auth";
import { AppFooter } from "@/features/instance-status";
import { Toaster } from "@/shared/ui/sonner";
import { TooltipProvider } from "@/shared/ui/tooltip";

export const Route = createRootRouteWithContext<RouterContext>()({
  component: function Root() {
    const session = useSession();
    return (
      <TooltipProvider>
        {/* Every page (app, auth, not found, errors) fills the window above the one footer. */}
        <div className="flex min-h-dvh flex-col bg-frame">
          <div className="flex flex-1 flex-col">
            <Outlet />
          </div>
          <AppFooter signedIn={session?.state === "signed_in"} />
        </div>
        <Toaster />
      </TooltipProvider>
    );
  },
});
