import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { applyPreferences, readPreferences } from "@/shared/lib/preferences";
import { createQueryClient } from "./query-client";
import { createAppRouter } from "./router";
import "./styles.css";
import "./icon-motion.css";

const Devtools = import.meta.env.DEV ? lazy(() => import("./devtools")) : () => null;

// index.html already did this before first paint; again here in case its script did not run.
applyPreferences(readPreferences());

const queryClient = createQueryClient();
const router = createAppRouter(queryClient);

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Suspense>
        <Devtools router={router} />
      </Suspense>
    </QueryClientProvider>
  </StrictMode>,
);
