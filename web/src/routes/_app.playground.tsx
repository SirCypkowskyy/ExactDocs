import { createFileRoute } from "@tanstack/react-router";
import { PlaygroundPage } from "@/features/playground";
import { useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { messages } from "./-messages";

export const Route = createFileRoute("/_app/playground")({
  component: function Playground() {
    usePageTitle(useMessages(messages).playgroundTitle);
    return <PlaygroundPage />;
  },
});
