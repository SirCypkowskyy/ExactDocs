import { KeyRound, LayoutList, Plug, Plus } from "lucide-react";
import type { HelpTopic } from "@/shared/ui/page-help";

/** The account page's tour. Targets are the `data-tour` values in the account route and tokens-section.tsx. */
export const accountHelp: HelpTopic = {
  title: { en: "Your account and agents", pl: "Twoje konto i agenci" },
  steps: [
    {
      icon: LayoutList,
      target: "account-tabs",
      title: { en: "Three tabs", pl: "Trzy karty" },
      body: {
        en: "How you sign in, the API tokens your agents use, and interface settings such as text size and theme.",
        pl: "Sposoby logowania, tokeny API, których używają twoi agenci, i ustawienia interfejsu, np. rozmiar tekstu i motyw.",
      },
      guide: "getting-started/accounts/",
    },
    {
      icon: Plus,
      target: "token-new",
      title: { en: "Create a token", pl: "Nowy token" },
      body: {
        en: "Name it, choose the libraries it reaches and when it expires. It is shown once, so copy it then.",
        pl: "Nadaj nazwę, wybierz biblioteki, do których sięga, i datę wygaśnięcia. Token widać tylko raz, więc wtedy go skopiuj.",
      },
      guide: "mcp/connect/#over-http",
    },
    {
      icon: KeyRound,
      target: "token-list",
      title: { en: "Your tokens", pl: "Twoje tokeny" },
      body: {
        en: "Each token's prefix, libraries, expiry and last use. Revoking one stops whatever uses it at once.",
        pl: "Prefiks, biblioteki, wygaśnięcie i ostatnie użycie każdego tokena. Unieważnienie od razu odcina wszystko, co go używa.",
      },
      guide: "rest-api/authentication/",
    },
    {
      icon: Plug,
      target: "mcp-config",
      title: { en: "Connect an agent", pl: "Podłączanie agenta" },
      body: {
        en: "Copy this into your MCP client and put your token where it says exd_YOUR_TOKEN.",
        pl: "Skopiuj to do klienta MCP i wstaw swój token w miejsce exd_YOUR_TOKEN.",
      },
      guide: "mcp/connect/",
    },
  ],
};
