import { createFileRoute, useRouter } from "@tanstack/react-router";
import { KeyRound, LogIn, SlidersHorizontal } from "lucide-react";
import { useCallback } from "react";
import {
  AccountPanel,
  LeaderboardOptIn,
  SignInSettings,
  usePreferencesStatus,
} from "@/features/auth";
import { parseTokensView, TokensSection } from "@/features/tokens";
import { useMessages } from "@/shared/lib/i18n";
import { InterfaceSettings } from "@/shared/ui/interface-settings";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/shared/ui/tabs";
import { messages } from "./-messages";

/** The tabs besides API tokens, which stays the default (no `tab` in the URL) so old links work. */
const TABS = ["sign-in", "interface"] as const;
type Tab = (typeof TABS)[number];
const isTab = (value: unknown): value is Tab => TABS.includes(value as Tab);

type AccountSearch = ReturnType<typeof parseTokensView> & {
  tab?: Tab | undefined;
  /** A provider link that just finished (#506): shown once, then dropped from the URL. */
  linked?: string | undefined;
  /** A provider link that came back refused, by its code. */
  link_error?: string | undefined;
};

/** The server only ever sends a provider name or a code: anything longer is not one of them. */
const shortText = (value: unknown) =>
  typeof value === "string" && value.length > 0 && value.length <= 100 ? value : undefined;

export const Route = createFileRoute("/_app/account")({
  // The URL holds the tab and the token table's view (search, filters, sort, page, size), so a
  // reload keeps them.
  validateSearch: (search: Record<string, unknown>): AccountSearch => ({
    ...parseTokensView(search),
    ...(isTab(search.tab) ? { tab: search.tab } : {}),
    // Set even when absent: the router hands a child route its parents' raw search too.
    linked: shortText(search.linked),
    link_error: shortText(search.link_error),
  }),
  component: function Account() {
    const router = useRouter();
    const { tab, linked, link_error, ...view } = Route.useSearch();
    const navigate = Route.useNavigate();
    const status = usePreferencesStatus();
    const t = useMessages(messages).account;
    const linkResult = linked !== undefined || link_error !== undefined;
    // Once the Sign-in tab has said how the link went, the URL forgets it (a reload says nothing).
    const forgetLinkResult = useCallback(
      () =>
        void navigate({
          search: (s) => ({ ...s, tab: "sign-in", linked: undefined, link_error: undefined }),
          replace: true,
        }),
      [navigate],
    );
    return (
      <AccountPanel onSignedOut={() => router.navigate({ to: "/sign-in", replace: true })}>
        <Tabs
          value={tab ?? (linkResult ? "sign-in" : "tokens")}
          onValueChange={(next) =>
            void navigate({
              search: isTab(next) ? { ...view, tab: next } : view,
              replace: true,
            })
          }
        >
          <TabsList aria-label={t.tabs}>
            <TabsTrigger value="sign-in">
              <LogIn aria-hidden="true" data-icon-motion="forward" />
              {t.signIn}
            </TabsTrigger>
            <TabsTrigger value="tokens">
              <KeyRound aria-hidden="true" data-icon-motion="tilt" />
              {t.tokens}
            </TabsTrigger>
            <TabsTrigger value="interface">
              <SlidersHorizontal aria-hidden="true" data-icon-motion="cog" />
              {t.interface}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="sign-in" className="pt-8 outline-none">
            <SignInSettings
              linked={linked}
              linkError={link_error}
              onLinkResultSeen={forgetLinkResult}
            />
          </TabsContent>
          <TabsContent value="tokens" className="pt-8 outline-none">
            <TokensSection />
          </TabsContent>
          <TabsContent value="interface" className="pt-8 outline-none">
            <InterfaceSettings status={status}>
              <LeaderboardOptIn />
            </InterfaceSettings>
          </TabsContent>
        </Tabs>
      </AccountPanel>
    );
  },
});
