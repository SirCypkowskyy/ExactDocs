import type { Language } from "@/shared/lib/i18n";

// Account | Role | Status | Created | Actions. Below `md` the pills sit under the name.
// Polish names the admin role "Administrator", which needs a wider role column than "Admin".
export const columnsFor = (language: Language) =>
  language === "pl"
    ? "md:grid md:grid-cols-[minmax(0,1fr)_6.75rem_6rem_7.5rem_auto] md:items-center md:gap-x-4"
    : "md:grid md:grid-cols-[minmax(0,1fr)_5rem_6rem_7.5rem_auto] md:items-center md:gap-x-4";
