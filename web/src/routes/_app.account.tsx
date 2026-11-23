import { createFileRoute, useRouter } from "@tanstack/react-router";
import { KeyRound, SlidersHorizontal } from "lucide-react";
import { AccountPanel, usePreferencesStatus } from "@/features/auth";
import { parseTokensView, TokensSection } from "@/features/tokens";
import { useMessages } from "@/shared/lib/i18n";
import { InterfaceSettings } from "@/shared/ui/interface-settings";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/shared/ui/tabs";
import { messages } from "./-messages";

type AccountSearch = ReturnType<typeof parseTokensView> & { tab?: "interface" | undefined };

export const Route = createFileRoute("/_app/account")({
  // The URL holds the tab and the token table's view (search, filters, sort, page, size), so a
  // reload keeps them.
  validateSearch: (search: Record<string, unknown>): AccountSearch => ({
    ...parseTokensView(search),
    ...(search.tab === "interface" ? { tab: "interface" as const } : {}),
  }),
  component: function Account() {
    const router = useRouter();
    const { tab, ...view } = Route.useSearch();
    const navigate = Route.useNavigate();
    const status = usePreferencesStatus();
    const t = useMessages(messages).account;
    return (
      <AccountPanel onSignedOut={() => router.navigate({ to: "/sign-in", replace: true })}>
        <Tabs
          value={tab ?? "tokens"}
          onValueChange={(next) =>
            void navigate({
              search: next === "interface" ? { ...view, tab: "interface" } : view,
              replace: true,
            })
          }
        >
          <TabsList aria-label={t.tabs}>
            <TabsTrigger value="tokens">
              <KeyRound aria-hidden="true" data-icon-motion="tilt" />
              {t.tokens}
            </TabsTrigger>
            <TabsTrigger value="interface">
              <SlidersHorizontal aria-hidden="true" data-icon-motion="cog" />
              {t.interface}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="tokens" className="pt-8 outline-none">
            <TokensSection />
          </TabsContent>
          <TabsContent value="interface" className="pt-8 outline-none">
            <InterfaceSettings status={status} />
          </TabsContent>
        </Tabs>
      </AccountPanel>
    );
  },
});
