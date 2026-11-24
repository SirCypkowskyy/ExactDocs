import type { ReactNode } from "react";
import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";

/**
 * The settings page around the sections: title, breadcrumb, section nav, the Details, Sharing and
 * Remove library sections, and the typed confirmation both removals use.
 */
export const pageMessages = defineMessages(
  {
    title: (name: string) => `${name} settings`,
    description: "Library settings",
    libraries: "Libraries",
    settings: "Settings",
    /** Said while the page loads (the skeleton). */
    loading: "Loading the library settings",
    onThisPage: "On this page",
    /** Each section's heading, and its entry in the section nav. */
    sections: {
      details: "Details",
      paths: "Files and tags",
      versions: "Versions",
      ai: "Retrieval and AI",
      sync: "Re-sync",
      sharing: "Sharing",
      danger: "Remove library",
    },
    unsavedMark: "(unsaved changes)",
    unsaved: (count: number) =>
      plural.en(count, {
        one: "# section has unsaved changes.",
        other: "# sections have unsaved changes.",
      }),
    details: {
      description: "The title and description people see for this library.",
      titleLabel: "Title",
      titleHint: "Shown in the library list and as the page heading.",
      descriptionLabel: "Description",
      descriptionHint: (most: number) =>
        `Shown on the library page. Up to ${most} characters, and it can be empty.`,
      editedNote:
        "Edited fields are kept when the library is re-imported. Fields you leave alone keep following the repository's README.",
      save: "Save changes",
      savedToast: "Saved the library details",
      noTitle: "Give the library a title.",
      titleTooLong: (most: number) => `Titles can be up to ${most} characters.`,
      descriptionTooLong: (most: number) => `Descriptions can be up to ${most} characters.`,
    },
    sharing: {
      description:
        "Who can find, read, change and manage this library. Its admins share it; its creator hands it over. The access log records every change.",
      manage: "Manage sharing",
      accessLog: "Access log",
    },
    danger: {
      description: "Take the library out of ExactDocs. The repository itself is never touched.",
      /** `id`: the library's ID, set in mono. */
      body: (id: ReactNode, count: number) => (
        <>
          Remove {id}
          {count > 0 && ` and its ${plural.en(count, { one: "version", other: "# versions" })}`}{" "}
          from browse, search and agents. You can add it again later.
        </>
      ),
      button: "Remove library…",
      /** `list`: the first versions, and how many more. */
      lossVersions: (count: number, list: string) =>
        `${plural.en(count, { one: "Its version", other: "All # versions" })} (${list}) and their articles disappear from browse, search and agents now.`,
      lossLibrary: "The library disappears from browse, search and agents now.",
      safe: "Nothing in the repository changes. Content that other libraries share stays available. You can add the library again.",
      confirm: "Remove library",
      removedToast: (id: string) => `Removed ${id}`,
      removedDescription:
        "It is gone from browse, search and agents. The repository was not touched.",
    },
    confirm: {
      /** `thing`: the version or the library ID, set in mono. */
      title: (thing: ReactNode) => <>Remove {thing}?</>,
      removing: "Removing",
    },
  },
  {
    title: (name) => `Ustawienia: ${name}`,
    description: "Ustawienia biblioteki",
    libraries: "Biblioteki",
    settings: "Ustawienia",
    loading: "Wczytywanie ustawień biblioteki",
    onThisPage: "Na tej stronie",
    sections: {
      details: "Szczegóły",
      paths: "Pliki i tagi",
      versions: "Wersje",
      ai: "Wyszukiwanie i AI",
      sync: "Ponowna synchronizacja",
      sharing: "Udostępnianie",
      danger: "Usuń bibliotekę",
    },
    unsavedMark: "(niezapisane zmiany)",
    unsaved: (count) =>
      plural.pl(count, {
        one: "# sekcja ma niezapisane zmiany.",
        few: "# sekcje mają niezapisane zmiany.",
        many: "# sekcji ma niezapisane zmiany.",
      }),
    details: {
      description: "Tytuł i opis, które widzą użytkownicy tej biblioteki.",
      titleLabel: "Tytuł",
      titleHint: "Widoczny na liście bibliotek i jako nagłówek strony.",
      descriptionLabel: "Opis",
      descriptionHint: (most) =>
        `Widoczny na stronie biblioteki. Może mieć do ${formatNumber(most, "pl")} znaków lub być pusty.`,
      editedNote:
        "Edytowane pola zostają zachowane przy ponownym imporcie biblioteki. Pola, których nie zmienisz, nadal są brane z README repozytorium.",
      save: "Zapisz zmiany",
      savedToast: "Zapisano szczegóły biblioteki",
      noTitle: "Nadaj bibliotece tytuł.",
      titleTooLong: (most) =>
        `Tytuł może mieć najwyżej ${plural.pl(most, { one: "# znak", few: "# znaki", many: "# znaków" })}.`,
      descriptionTooLong: (most) =>
        `Opis może mieć najwyżej ${plural.pl(most, { one: "# znak", few: "# znaki", many: "# znaków" })}.`,
    },
    sharing: {
      description:
        "Kto może znaleźć tę bibliotekę, czytać ją, zmieniać i nią zarządzać. Udostępniają ją jej administratorzy, a jej twórca może przekazać ją innej osobie. Dziennik dostępu zapisuje każdą zmianę.",
      manage: "Zarządzaj udostępnianiem",
      accessLog: "Dziennik dostępu",
    },
    danger: {
      description: "Usuń bibliotekę z ExactDocs. Samo repozytorium nigdy nie jest zmieniane.",
      body: (id, count) => (
        <>
          Usuń bibliotekę {id}
          {count > 0 &&
            ` wraz z ${plural.pl(count, { one: "jej wersją", few: "jej # wersjami", many: "jej # wersjami" })}`}
          . Zniknie z przeglądania i wyszukiwania, a agenci stracą do niej dostęp. Możesz ją później
          dodać ponownie.
        </>
      ),
      button: "Usuń bibliotekę…",
      lossVersions: (count, list) =>
        `${plural.pl(count, { one: "Jej wersja", few: "Wszystkie # wersje", many: "Wszystkie # wersji" })} (${list}) i ich artykuły od razu znikają z przeglądania i wyszukiwania, a agenci tracą do nich dostęp.`,
      lossLibrary:
        "Biblioteka od razu znika z przeglądania i wyszukiwania, a agenci tracą do niej dostęp.",
      safe: "W repozytorium nic się nie zmienia. Treść współdzielona z innymi bibliotekami pozostaje dostępna. Możesz ponownie dodać tę bibliotekę.",
      confirm: "Usuń bibliotekę",
      removedToast: (id) => `Usunięto ${id}`,
      removedDescription:
        "Zniknęła z przeglądania i wyszukiwania, a agenci stracili do niej dostęp. Repozytorium pozostało nietknięte.",
    },
    confirm: {
      title: (thing) => <>Usunąć {thing}?</>,
      removing: "Usuwanie",
    },
  },
);
