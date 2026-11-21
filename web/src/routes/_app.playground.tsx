import { createFileRoute } from "@tanstack/react-router";
import { PlaygroundPage } from "@/features/playground";
import { usePageTitle } from "@/shared/lib/use-page-title";

export const Route = createFileRoute("/_app/playground")({
  component: function Playground() {
    usePageTitle("Search playground");
    return <PlaygroundPage />;
  },
});
