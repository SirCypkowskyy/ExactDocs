import type { ReactNode } from "react";
import { defineMessages } from "@/shared/lib/i18n";

/*
 * The sharing slice's strings: the grants table, the share, transfer and remove dialogs, and the
 * sentences that explain a refusal. Usernames, group names and server details stay as they are.
 */

type Role = "viewer" | "contributor" | "admin" | "creator";
type Kind = "user" | "group";
/** Whom a sentence names: a user by name, a group as "the group …". */
interface Who {
  kind: Kind;
  subject: string;
}

const isRole = (role: string): role is Role =>
  role === "viewer" || role === "contributor" || role === "admin" || role === "creator";

const ROLE_LOWER: Record<Role, string> = {
  viewer: "viewer",
  contributor: "contributor",
  admin: "admin",
  creator: "creator",
};
const roleLowerEn = (role: string) => (isRole(role) ? ROLE_LOWER[role] : role.toLowerCase());
/** "a viewer", "an admin". */
const articleEn = (role: string) => {
  const name = roleLowerEn(role);
  return `${/^[aeiou]/.test(name) ? "an" : "a"} ${name}`;
};
const whoEn = (w: Who) => (w.kind === "group" ? `the group ${w.subject}` : w.subject);
/** `who` at the start of a sentence: a username keeps its letter case. */
const whoFirstEn = (w: Who) => (w.kind === "group" ? `The group ${w.subject}` : w.subject);

/** Polish: "jest teraz czytelnikiem" (instrumental), "traci rolę czytelnika" (genitive). */
const ROLE_INSTRUMENTAL: Record<Role, string> = {
  viewer: "czytelnikiem",
  contributor: "współtwórcą",
  admin: "administratorem",
  creator: "twórcą",
};
const ROLE_GENITIVE: Record<Role, string> = {
  viewer: "czytelnika",
  contributor: "współtwórcy",
  admin: "administratora",
  creator: "twórcy",
};
const rolePl = (forms: Record<Role, string>, role: string) => (isRole(role) ? forms[role] : role);
/** "Grupa corp:docs" / "bob" at the start of a sentence. */
const whoFirstPl = (w: Who) => (w.kind === "group" ? `Grupa ${w.subject}` : w.subject);
/** "grupy corp:docs" / "użytkownika bob": whose role or access. */
const whosePl = (w: Who) =>
  w.kind === "group" ? `grupy ${w.subject}` : `użytkownika ${w.subject}`;

export const messages = defineMessages(
  {
    roles: {
      viewer: "Viewer",
      contributor: "Contributor",
      admin: "Admin",
      creator: "Creator",
    },
    /** What each role that can be given adds (the backend's rules, docs/rest-api.md). */
    roleHints: {
      viewer: "Finds, reads and searches it, in the UI and over MCP.",
      contributor: "Also imports versions, re-syncs it and tags articles.",
      admin: "Also changes its settings, removes versions and shares it.",
    },
    kinds: { user: "User", group: "Group" },
    kindsPlural: { user: "Users", group: "Groups" },
    page: {
      title: "Sharing",
      documentTitle: (name: string) => `Sharing ${name}`,
      description: "Who can find, read, change and manage it.",
      accessLog: "Access log",
      transfer: "Transfer ownership",
      share: "Share",
      breadcrumb: "Breadcrumb",
      libraries: "Libraries",
      noCreator: "No creator: it was added before library roles, so operators manage it.",
      createdBy: (creator: ReactNode) => (
        <>Created by {creator}, who alone makes or removes admins and can hand it over.</>
      ),
      loading: "Loading who has access",
      adminsOnlyTitle: "Only the library's admins manage its sharing",
      adminsOnly:
        "Ask its creator or an operator to make you an admin, or to share it with the people you have in mind.",
      emptyTitle: "Not shared with anyone yet",
      empty:
        "Only operators can see it for now. Share it with people or identity-provider groups as viewers, contributors or admins.",
    },
    /** What the live region and the toast say once a change is stored. */
    done: {
      nowRole: (who: Who, role: string) => `${whoFirstEn(who)} is now ${articleEn(role)}.`,
      nowCreator: (username: string, library: string) =>
        `${username} is now the creator of ${library}.`,
      noAccess: (who: Who) => `${whoFirstEn(who)} no longer has access.`,
      roleFailed: (who: Who, why: string) => `Couldn't change the role of ${whoEn(who)}. ${why}`,
    },
    table: {
      label: "Who has access",
      who: "Who",
      kind: "Kind",
      role: "Role",
      actions: "Actions",
      roleOf: (subject: string) => `Role of ${subject}`,
      remove: (subject: string) => `Remove ${subject}`,
      find: "Find a person or group",
      findPlaceholder: "Username or group",
      anyKind: "Any",
      anyRole: "Any",
      nobody: "Nobody matches.",
      clearFilters: "Clear filters",
    },
    remove: {
      title: (who: Who | undefined) => (who ? `Remove ${whoEn(who)}?` : "Remove access?"),
      loses: (who: Who, role: string) => `${whoFirstEn(who)} loses the ${roleLowerEn(role)} role. `,
      description:
        "Access ends at once, on the web and over MCP, unless another grant or a group still gives one.",
    },
    share: {
      title: (library: string) => `Share ${library}`,
      description:
        "Give a person or an identity-provider group a role. Someone who already has one gets the new role instead.",
      with: "Share with",
      person: "A person",
      group: "A group",
      username: "Username",
      groupName: "Group",
      groupHint:
        "As your identity provider reports it, prefix included (corp:docs). Letter case matters.",
      role: "Role",
      creatorOnly: "Only the library's creator makes someone an admin.",
      enterUsername: "Enter a username.",
      enterGroup: "Enter a group's name.",
      submit: "Share",
    },
    transfer: {
      title: (library: string) => `Transfer ${library}`,
      description:
        "The new creator owns the library: only they make or remove admins, and only they can hand it over again. Its creator now, if it has one, stays on as an admin.",
      username: "New creator's username",
      enterUsername: "Enter the username of the new creator.",
      submit: "Transfer ownership",
    },
    /** One sentence a person can act on, for any failure of the sharing API. */
    errors: {
      offline: "Can't reach the server. Check your connection and try again.",
      creatorOnly:
        "Only the library's creator can do that: give or take away the admin role, or transfer it.",
      adminOnly: "Only an admin of this library can see or change who it is shared with.",
      unknownAccount:
        "No account has that username. Check the spelling, or ask an operator to create it.",
      unknownGrant: "That role was already taken away. The list has been refreshed.",
      alreadyCreator: "That user is already the creator of this library.",
      creatorRole: "The creator's role isn't changed here. Transfer the library instead.",
      notFound: "This library no longer exists, or you can't see it.",
      sessionEnded: "Your session ended. Sign in again to manage sharing.",
      refusedField: (field: string, message: string) => `The server refused ${field}: ${message}.`,
      refused: (message: string) => `The server refused the request: ${message}.`,
      other: (status: number) => `Something went wrong (${status}). Try again.`,
    },
  },
  {
    roles: {
      viewer: "Czytelnik",
      contributor: "Współtwórca",
      admin: "Administrator",
      creator: "Twórca",
    },
    roleHints: {
      viewer: "Znajduje, czyta i przeszukuje bibliotekę w interfejsie i przez MCP.",
      contributor: "Dodatkowo importuje wersje, ponownie ją synchronizuje i taguje artykuły.",
      admin: "Dodatkowo zmienia jej ustawienia, usuwa wersje i ją udostępnia.",
    },
    kinds: { user: "Użytkownik", group: "Grupa" },
    kindsPlural: { user: "Użytkownicy", group: "Grupy" },
    page: {
      title: "Udostępnianie",
      documentTitle: (name) => `Udostępnianie: ${name}`,
      description: "Kto może ją znaleźć, czytać, zmieniać i nią zarządzać.",
      accessLog: "Dziennik dostępu",
      transfer: "Przekaż własność",
      share: "Udostępnij",
      breadcrumb: "Ścieżka nawigacyjna",
      libraries: "Biblioteki",
      noCreator:
        "Brak twórcy: biblioteka została dodana przed wprowadzeniem ról bibliotek, więc zarządzają nią operatorzy.",
      createdBy: (creator) => (
        <>
          Twórca: {creator}. Tylko twórca nadaje i odbiera rolę administratora oraz może przekazać
          bibliotekę.
        </>
      ),
      loading: "Wczytywanie listy osób z dostępem",
      adminsOnlyTitle: "Udostępnianiem biblioteki zarządzają tylko jej administratorzy",
      adminsOnly:
        "Poproś twórcę biblioteki lub operatora o rolę administratora albo o udostępnienie jej wybranym osobom.",
      emptyTitle: "Jeszcze nikomu nie udostępniono",
      empty:
        "Na razie widzą ją tylko operatorzy. Udostępnij ją osobom lub grupom dostawcy tożsamości jako czytelnikom, współtwórcom lub administratorom.",
    },
    done: {
      nowRole: (who, role) => `${whoFirstPl(who)} jest teraz ${rolePl(ROLE_INSTRUMENTAL, role)}.`,
      nowCreator: (username, library) => `${username} jest teraz twórcą biblioteki ${library}.`,
      noAccess: (who) => `${whoFirstPl(who)} nie ma już dostępu.`,
      roleFailed: (who, why) => `Nie udało się zmienić roli ${whosePl(who)}. ${why}`,
    },
    table: {
      label: "Kto ma dostęp",
      who: "Kto",
      kind: "Rodzaj",
      role: "Rola",
      actions: "Akcje",
      roleOf: (subject) => `Rola: ${subject}`,
      remove: (subject) => `Usuń: ${subject}`,
      find: "Znajdź osobę lub grupę",
      findPlaceholder: "Nazwa użytkownika lub grupa",
      anyKind: "Dowolny",
      anyRole: "Dowolna",
      nobody: "Nikogo nie znaleziono.",
      clearFilters: "Wyczyść filtry",
    },
    remove: {
      title: (who) => (who ? `Usunąć dostęp ${whosePl(who)}?` : "Usunąć dostęp?"),
      loses: (who, role) => `${whoFirstPl(who)} traci rolę ${rolePl(ROLE_GENITIVE, role)}. `,
      description:
        "Dostęp kończy się natychmiast, w przeglądarce i przez MCP, chyba że nadal daje go inne uprawnienie lub grupa.",
    },
    share: {
      title: (library) => `Udostępnij ${library}`,
      description:
        "Nadaj rolę osobie lub grupie dostawcy tożsamości. Jeśli ktoś ma już rolę, otrzyma nową w jej miejsce.",
      with: "Komu udostępnić",
      person: "Osobie",
      group: "Grupie",
      username: "Nazwa użytkownika",
      groupName: "Grupa",
      groupHint:
        "Tak, jak podaje ją Twój dostawca tożsamości, razem z prefiksem (corp:docs). Wielkość liter ma znaczenie.",
      role: "Rola",
      creatorOnly: "Tylko twórca biblioteki może nadać komuś rolę administratora.",
      enterUsername: "Wpisz nazwę użytkownika.",
      enterGroup: "Wpisz nazwę grupy.",
      submit: "Udostępnij",
    },
    transfer: {
      title: (library) => `Przekaż ${library}`,
      description:
        "Nowy twórca staje się właścicielem biblioteki: tylko on nadaje i odbiera rolę administratora i tylko on może ją ponownie przekazać. Obecny twórca, jeśli jest, pozostaje administratorem.",
      username: "Nazwa użytkownika nowego twórcy",
      enterUsername: "Wpisz nazwę użytkownika nowego twórcy.",
      submit: "Przekaż własność",
    },
    errors: {
      offline: "Nie można połączyć się z serwerem. Sprawdź połączenie i spróbuj ponownie.",
      creatorOnly:
        "Tylko twórca biblioteki może to zrobić: nadać lub odebrać rolę administratora albo przekazać bibliotekę.",
      adminOnly:
        "Tylko administrator tej biblioteki może zobaczyć lub zmienić, komu jest udostępniona.",
      unknownAccount:
        "Żadne konto nie ma takiej nazwy użytkownika. Sprawdź pisownię lub poproś operatora o utworzenie konta.",
      unknownGrant: "Ta rola została już odebrana. Lista została odświeżona.",
      alreadyCreator: "Ten użytkownik jest już twórcą tej biblioteki.",
      creatorRole: "Roli twórcy nie zmienia się tutaj. Zamiast tego przekaż bibliotekę.",
      notFound: "Ta biblioteka już nie istnieje albo nie masz do niej dostępu.",
      sessionEnded: "Twoja sesja wygasła. Zaloguj się ponownie, aby zarządzać udostępnianiem.",
      refusedField: (field, message) => `Serwer odrzucił pole ${field}: ${message}.`,
      refused: (message) => `Serwer odrzucił żądanie: ${message}.`,
      other: (status) => `Coś poszło nie tak (${status}). Spróbuj ponownie.`,
    },
  },
);

export type SharingMessages = (typeof messages)["en"];

/** A role as people read it; a role the client does not know, as the server named it. */
export const roleLabel = (t: SharingMessages, role: string): string =>
  isRole(role) ? t.roles[role] : role;
