import { defineMessages } from "@/shared/lib/i18n";

// The `-` prefix keeps the router's file scanner from taking this file for a route.

/** Words the routes themselves show: page titles and the account page's tabs. */
export const messages = defineMessages(
  {
    account: { tabs: "Account", tokens: "API tokens", interface: "Interface" },
    searchTitle: "Search",
    searchFor: (q: string) => `Search: ${q}`,
  },
  {
    account: { tabs: "Konto", tokens: "Tokeny API", interface: "Interfejs" },
    searchTitle: "Wyszukiwanie",
    searchFor: (q) => `Wyszukiwanie: ${q}`,
  },
);
