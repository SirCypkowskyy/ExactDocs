import { defineMessages, formatNumber } from "@/shared/lib/i18n";

/** Words more than one settings section says the same way. */
export const sharedMessages = defineMessages(
  {
    saving: "Saving",
    saved: "Saved.",
    retry: "Retry",
    queueing: "Queueing",
    /** The first refs of a long list, and how many more there are. */
    andMore: (list: string, more: number) => (more > 0 ? `${list}, and ${more} more` : list),
  },
  {
    saving: "Zapisywanie",
    saved: "Zapisano.",
    retry: "Ponów",
    queueing: "Dodawanie do kolejki",
    andMore: (list, more) => (more > 0 ? `${list} i jeszcze ${formatNumber(more, "pl")}` : list),
  },
);
