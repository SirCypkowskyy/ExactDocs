import type { ReactNode } from "react";
import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";

/** The Re-sync section, and what a re-sync did to each version. */
export const syncMessages = defineMessages(
  {
    description:
      "Check the repository for new commits on each branch version and import only what changed. Tags and commits are pinned: a tag that moved upstream is reported, and re-imported only when you confirm it.",
    checking: "Checking",
    syncNow: "Re-sync now",
    finished: "Re-sync finished",
    failed: "Re-sync failed",
    /** `time`: when it was checked, as a relative <time>. */
    checked: (time: ReactNode) => <>Checked {time}.</>,
    versions: "Versions",
    reimport: "Re-import the new commit",
    reimportOf: (ref: string) => `of ${ref}`,
    commitChange: "(previous commit to new commit)",
    /** `refs`: the pinned versions, comma-separated. */
    pinned: (refs: string, count: number) =>
      `${refs} ${plural.en(count, { one: "is pinned and never changes", other: "are pinned and never change" })}.`,
    status: {
      queued: "Updating",
      up_to_date: "Up to date",
      importing: "Already importing",
      pinned: "Pinned",
      failed: "Failed",
      cancelled: "Left alone: its sync was cancelled",
    },
    failure: {
      tagDeleted: "The tag is gone from the repository. The version keeps serving what it had.",
      branchDeleted:
        "The branch is gone from the repository. The version keeps serving what it had.",
      tagMoved:
        "The tag now points at another commit. It is not re-imported unless you confirm it. The version keeps serving what it had.",
      unexpected: "Its import could not be queued. The version keeps serving what it had.",
      other: "It could not be synced. The version keeps serving what it had.",
    },
    headline: {
      changes: (queued: number, failed: number) =>
        `${[
          queued > 0 &&
            `${plural.en(queued, { one: "# version is", other: "# versions are" })} updating`,
          failed > 0 &&
            plural.en(failed, {
              one: "# version could not be checked",
              other: "# versions could not be checked",
            }),
        ]
          .filter(Boolean)
          .join(", ")}.`,
      importing: "An import is already running.",
      allPinned: "Nothing to update: every version is pinned.",
      upToDate: "Everything is up to date.",
    },
  },
  {
    description:
      "Sprawdź, czy w gałęziach, z których pochodzą wersje, pojawiły się nowe commity, i zaimportuj tylko to, co się zmieniło. Tagi i commity są przypięte: tag przesunięty w repozytorium zostanie zgłoszony i ponownie zaimportowany dopiero wtedy, gdy to potwierdzisz.",
    checking: "Sprawdzanie",
    syncNow: "Synchronizuj teraz",
    finished: "Synchronizacja zakończona",
    failed: "Synchronizacja nie powiodła się",
    checked: (time) => <>Sprawdzono {time}.</>,
    versions: "Wersje",
    reimport: "Zaimportuj nowy commit",
    reimportOf: (ref) => `dla ${ref}`,
    commitChange: "(z poprzedniego commitu na nowy)",
    pinned: (refs, count) =>
      `${refs} ${plural.pl(count, {
        one: "jest przypięta i nigdy się nie zmienia",
        few: "są przypięte i nigdy się nie zmieniają",
        many: "są przypięte i nigdy się nie zmieniają",
      })}.`,
    status: {
      queued: "Aktualizowana",
      up_to_date: "Aktualna",
      importing: "Już importowana",
      pinned: "Przypięta",
      failed: "Błąd",
      cancelled: "Bez zmian: synchronizację anulowano",
    },
    failure: {
      tagDeleted: "Tagu nie ma już w repozytorium. Wersja nadal udostępnia to, co miała.",
      branchDeleted: "Gałęzi nie ma już w repozytorium. Wersja nadal udostępnia to, co miała.",
      tagMoved:
        "Tag wskazuje teraz inny commit. Nie zostanie ponownie zaimportowany, dopóki tego nie potwierdzisz. Wersja nadal udostępnia to, co miała.",
      unexpected:
        "Nie udało się dodać jej importu do kolejki. Wersja nadal udostępnia to, co miała.",
      other: "Nie udało się jej zsynchronizować. Wersja nadal udostępnia to, co miała.",
    },
    headline: {
      changes: (queued, failed) => {
        const updating =
          queued > 0 &&
          plural.pl(queued, {
            one: "# wersja jest aktualizowana",
            few: "# wersje są aktualizowane",
            many: "# wersji jest aktualizowanych",
          });
        // A negated verb takes the genitive whatever the count: 1, 2 or 5 „wersji”.
        const count = formatNumber(failed, "pl");
        if (!updating) return `Nie udało się sprawdzić ${count} wersji.`;
        return failed > 0
          ? `${updating}, nie udało się sprawdzić ${count} wersji.`
          : `${updating}.`;
      },
      importing: "Import już trwa.",
      allPinned: "Nie ma nic do zaktualizowania: każda wersja jest przypięta.",
      upToDate: "Wszystko jest aktualne.",
    },
  },
);
