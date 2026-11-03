import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { TanStackRouterDevtools } from "@tanstack/react-router-devtools";
import type { AppRouter } from "./router";

/** Dev-only tooling. Loaded lazily from main.tsx so it never ships in the production bundle. */
export default function Devtools({ router }: { router: AppRouter }) {
  return (
    <>
      <ReactQueryDevtools buttonPosition="bottom-left" />
      <TanStackRouterDevtools router={router} position="bottom-right" />
    </>
  );
}
