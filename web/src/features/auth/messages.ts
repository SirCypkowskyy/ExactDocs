import { defineMessages, plural } from "@/shared/lib/i18n";

/** The auth slice's strings: the shell, sign-in and setup, the account panel, error screens. */
export const messages = defineMessages(
  {
    nav: {
      main: "Main",
      libraries: "Libraries",
      librariesHint: "Every imported library, its versions and its sync state.",
      search: "Search",
      searchHint: "One query across the default version of every library.",
      tools: "Tools",
      playground: "Playground",
      playgroundHint: "Compare text, vector, hybrid and agentic search side by side.",
      jobs: "Jobs",
      jobsHint: "Imports, re-syncs and embedding runs, with their progress.",
      leaderboard: "Leaderboard",
      leaderboardHint: "The most-read libraries this day, week, month or year.",
      admin: "Admin",
      overview: "Overview",
      overviewHint: "Figures, charts and what needs attention on this instance.",
      ai: "AI",
      aiHint: "Model providers, budgets and what retrieval has spent.",
      users: "Users",
      usersHint: "Accounts, roles and how people sign in.",
      accessLog: "Access log",
      accessLogHint: "Which token read which library, and when.",
      menu: "Menu",
      sheetDescription: "Pages and your account",
      skipToContent: "Skip to content",
      home: "ExactDocs, libraries",
      searchAll: "Search all libraries",
    },
    account: {
      menuLabel: (name: string) => `Account: ${name}`,
      accountAndTokens: "Account and API tokens",
      title: "Account",
      description:
        "Who you are signed in as, and the tokens that let an agent read documentation for you.",
      signedInAs: "Signed in as",
      username: "Username",
      role: "Role",
      signedIn: "Signed in",
      throughAccess: "through Cloudflare Access",
    },
    roles: { admin: "Admin", member: "Member" } as Record<string, string>,
    signOut: {
      action: "Sign out",
      pending: "Signing out",
      pendingMenu: "Signing out…",
      failed: "Couldn't sign out. Try again.",
      accessHint: "Signs you out of Cloudflare Access",
    },
    layout: {
      tagline: "Documentation, word for word: every answer names its library, version and commit.",
    },
    signIn: {
      title: "Sign in",
      intro: "Sign in to this ExactDocs server.",
      username: "Username",
      password: "Password",
      submit: "Sign in",
      busy: "Signing in",
      or: "or",
      withProvider: (name: string) => `Sign in with ${name}`,
    },
    setup: {
      title: "Create the admin account",
      intro: "First run. This account becomes the admin of this server.",
      username: "Username",
      password: "Password",
      passwordHint: (min: number) =>
        `At least ${min} characters. A short phrase of unrelated words works well.`,
      confirm: "Repeat the password",
      submit: "Create account and sign in",
      busy: "Creating account",
    },
    validation: {
      enterUsername: "Enter your username.",
      enterPassword: "Enter your password.",
      chooseUsername: "Choose a username.",
      atMost: (n: number) => `Use at most ${n} characters.`,
      atLeast: (n: number) => `Use at least ${n} characters.`,
      noSpaces: "No spaces, please.",
      mismatch: "The passwords don't match.",
    },
    refusal: {
      appNotApproved: (org: string) =>
        `The organization ${org} has not approved this app. Ask an organization owner to approve the ExactDocs OAuth App in GitHub settings.`,
      ssoRequired: (org: string) =>
        `Please authorize SSO for ${org}. Authorize the ExactDocs OAuth App for your organization in GitHub settings, then try again.`,
      orgDenied: (org: string) =>
        `The organization ${org} refused access. Ask an organization owner to check the ExactDocs OAuth App permissions.`,
      teamRequired:
        "You are not a member of an allowed team. Ask an organization owner to add you to a team allowed to use this server.",
      orgRequired:
        "You are not a member of an allowed organization. Ask an organization owner to check your membership.",
      revoked: "Your identity provider revoked this sign-in. Sign in again to authorize access.",
      notAllowed:
        "Your identity provider signed you in, but you are not in a group allowed to use this server. Ask an admin to add you.",
      disabled: "Your account is disabled. Ask an admin to enable it.",
      usernameTaken:
        "No account could be created for you: your username is taken. Ask an admin for help.",
      providerDown:
        "Your identity provider can't be reached right now. Try again in a moment, or sign in with a password.",
      cancelled: "Your identity provider did not sign you in. Try again.",
      failed: "The sign-in could not be completed. Start it again from this page.",
      notLinked:
        "That identity is not linked to an account on this server. Sign in another way, then link it under Account, Sign-in.",
    },
    errors: {
      adminCreated: "The admin account was created, but signing in failed.",
      signIn: "Sign in",
      unreachable: "Can't reach the server. Check your connection and try again.",
      invalidCredentials: "That username and password don't match.",
      waitLittle: "Wait a little, then try again.",
      tryAgainIn: (seconds: number) =>
        `Try again in ${seconds} ${seconds === 1 ? "second" : "seconds"}.`,
      tooMany: (when: string) => `Too many failed sign-ins. ${when}`,
      alreadySetUp: "This server already has an admin.",
      signInInstead: "Sign in instead",
      setupRequired: "This server has no admin yet.",
      setItUp: "Set it up",
      server: (status: number) =>
        `Something went wrong on the server (${status}). Try again in a moment.`,
    },
    screens: {
      notFound: "Page not found",
      nothingHere: "There is nothing at this address.",
      backToLibraries: "Back to libraries",
      somethingWrong: "Something went wrong",
      cantReach: "Can't reach the server",
      didntAnswer: "ExactDocs didn't answer. Check that it is running, then try again.",
      tryAgain: "Try again",
      loading: "Loading ",
    },
    preferences: {
      browser: "Kept in this browser. Sign in to keep them with your account.",
      saving: "Saving to your account…",
      saved: "Saved to your account, so they follow you to any browser.",
      unavailable: "Kept in this browser: this server does not store interface preferences yet.",
      error: "Couldn't save to your account. Your choices still apply in this browser.",
    },
    password: {
      title: "Password",
      description:
        "Change the password you sign in with. Your other sessions end; this one stays signed in, and your API tokens keep working.",
      current: "Current password",
      next: "New password",
      confirm: "Repeat the new password",
      hint: (min: number, max: number) =>
        `${min} to ${max} characters. A short phrase of unrelated words works well.`,
      show: {
        current: "Show current password",
        next: "Show new password",
        confirm: "Show repeated password",
      },
      hide: {
        current: "Hide current password",
        next: "Hide new password",
        confirm: "Hide repeated password",
      },
      submit: "Change password",
      busy: "Changing password",
      changed: "Password changed. Your other sessions were signed out.",
      toast: "Password changed",
      toastHint: "Your other sessions were signed out. Your API tokens keep working.",
      enterCurrent: "Enter your current password.",
      wait: {
        seconds: (n: number) =>
          `Try again in ${plural.en(n, { one: "# second", other: "# seconds" })}.`,
        minutes: (n: number) =>
          `Try again in ${plural.en(n, { one: "# minute", other: "# minutes" })}.`,
        hours: (n: number) => `Try again in ${plural.en(n, { one: "# hour", other: "# hours" })}.`,
      },
      errors: {
        wrongPassword: "That isn't your current password.",
        tooMany: (when: string) => `Too many wrong passwords. ${when}`,
        waitLittle: "Wait a little, then try again.",
        external:
          "This account signs in through an identity provider, so it has no password to change.",
        sessionEnded: "Your session has ended.",
        signIn: "Sign in again",
        newRefused: (min: number, max: number) =>
          `The server refused this password. Use ${min} to ${max} characters.`,
      },
      none: {
        access:
          "You sign in through Cloudflare Access, so there is no ExactDocs password to change here.",
        provider: (name: string) =>
          `You sign in with ${name}, so there is no ExactDocs password to change here.`,
        providers:
          "You sign in through an identity provider, so there is no ExactDocs password to change here.",
      },
    },
    providers: {
      title: "Linked sign-in providers",
      description:
        "Link another way to sign in to this same account. Nothing else changes: your role and groups stay as they are.",
      loading: "Loading sign-in providers",
      loadFailed: "Couldn't load your sign-in providers.",
      list: "Sign-in providers",
      linked: "Linked",
      linkedSince: (date: string) => `Linked · since ${date}`,
      origin: "Created your account",
      notLinked: "Not linked",
      notConfigured: "No longer offered by this server",
      link: (name: string) => `Link ${name}`,
      unlink: "Unlink",
      unlinkName: (name: string) => `Unlink ${name}`,
      cannotUnlink: (name: string) =>
        `This is your only way to sign in: the account was created with ${name} and has no password, so it can't be unlinked.`,
      confirmTitle: (name: string) => `Unlink ${name}?`,
      confirmBody: (name: string) =>
        `You will no longer be able to sign in with ${name}. The sessions you have now stay signed in, and you can link it again later.`,
      confirm: "Unlink",
      pending: "Unlinking",
      unlinkedToast: (name: string) => `${name} unlinked`,
      linkedToast: (name: string) => `${name} linked`,
      linkedToastHint: (name: string) => `You can now sign in with ${name}.`,
      linkedGeneric: "Sign-in provider linked",
      linkErrors: {
        elsewhere:
          "That identity is already linked to another ExactDocs account. Unlink it there first, or sign in with it to use that account.",
        alreadyLinked:
          "This account already has an identity of that provider. Unlink it first to link a different one.",
        notAllowed:
          "The provider signed you in, but that identity is not in a group allowed to use this server, so it was not linked.",
        notLinked: "That identity could not be linked to this account. Start again from this page.",
        cancelled: "The provider did not confirm the link, so nothing changed. Try again.",
        sessionEnded: "Your session ended before the link finished, so nothing changed.",
        signIn: "Sign in again",
        unavailable: "The provider can't be reached right now. Try again in a moment.",
        failed:
          "The link could not be completed, so nothing changed. Start it again from this page.",
      },
      errors: {
        unreachable: "Can't reach the server. Check your connection and try again.",
        alreadyLinked: (name: string) => `${name} is already linked to this account.`,
        unknown: (name: string) => `${name} is no longer offered by this server.`,
        unavailable: (name: string) => `${name} can't be reached right now. Try again in a moment.`,
        notLinked: (name: string) => `${name} was not linked any more.`,
        lastMethod: (name: string) =>
          `${name} is your only way to sign in, so it can't be unlinked.`,
        sessionEnded: "Your session has ended.",
        signIn: "Sign in again",
        server: (status: number) =>
          `Something went wrong on the server (${status}). Try again in a moment.`,
      },
    },
    leaderboard: {
      label: "Show me on the leaderboard",
      description:
        "Lets people on this server see your username with how many documents you read, searched and asked about. Only counts are shown, never what you read or searched for.",
      on: "The people leaderboard is on.",
      off: "The people leaderboard is off on this server, so nobody is shown by name. Your choice is kept for when an operator turns it on.",
      unavailable: "Your account's choice couldn't be loaded, so it can't be changed right now.",
    },
  },
  {
    nav: {
      main: "Główna",
      libraries: "Biblioteki",
      librariesHint: "Wszystkie zaimportowane biblioteki, ich wersje i stan synchronizacji.",
      search: "Wyszukiwanie",
      searchHint: "Jedno zapytanie w domyślnej wersji każdej biblioteki.",
      tools: "Narzędzia",
      playground: "Piaskownica",
      playgroundHint:
        "Porównaj obok siebie wyszukiwanie tekstowe, wektorowe, hybrydowe i agentowe.",
      jobs: "Zadania",
      jobsHint: "Importy, ponowne synchronizacje i przebiegi embeddingu wraz z postępem.",
      leaderboard: "Ranking",
      leaderboardHint: "Najczęściej czytane biblioteki dnia, tygodnia, miesiąca lub roku.",
      admin: "Administracja",
      overview: "Przegląd",
      overviewHint: "Liczby, wykresy i to, co na tej instancji wymaga uwagi.",
      ai: "AI",
      aiHint: "Dostawcy modeli, budżety i to, ile wydało wyszukiwanie.",
      users: "Użytkownicy",
      usersHint: "Konta, role i sposoby logowania.",
      accessLog: "Dziennik dostępu",
      accessLogHint: "Który token czytał którą bibliotekę i kiedy.",
      menu: "Menu",
      sheetDescription: "Strony i Twoje konto",
      skipToContent: "Przejdź do treści",
      home: "ExactDocs, biblioteki",
      searchAll: "Szukaj we wszystkich bibliotekach",
    },
    account: {
      menuLabel: (name) => `Konto: ${name}`,
      accountAndTokens: "Konto i tokeny API",
      title: "Konto",
      description:
        "Konto, na którym pracujesz, i tokeny, dzięki którym agent czyta dla Ciebie dokumentację.",
      signedInAs: "Zalogowano jako",
      username: "Nazwa użytkownika",
      role: "Rola",
      signedIn: "Logowanie",
      throughAccess: "przez Cloudflare Access",
    },
    roles: { admin: "Administrator", member: "Członek" },
    signOut: {
      action: "Wyloguj się",
      pending: "Wylogowywanie",
      pendingMenu: "Wylogowywanie…",
      failed: "Nie udało się wylogować. Spróbuj ponownie.",
      accessHint: "Wylogowuje z Cloudflare Access",
    },
    layout: {
      tagline:
        "Dokumentacja słowo w słowo: każda odpowiedź podaje swoją bibliotekę, wersję i commit.",
    },
    signIn: {
      title: "Zaloguj się",
      intro: "Zaloguj się do tego serwera ExactDocs.",
      username: "Nazwa użytkownika",
      password: "Hasło",
      submit: "Zaloguj się",
      busy: "Logowanie",
      or: "lub",
      withProvider: (name) => `Zaloguj się przez ${name}`,
    },
    setup: {
      title: "Utwórz konto administratora",
      intro: "Pierwsze uruchomienie. To konto zostanie administratorem tego serwera.",
      username: "Nazwa użytkownika",
      password: "Hasło",
      passwordHint: (min) =>
        `Co najmniej ${plural.pl(min, { one: "# znak", few: "# znaki", many: "# znaków" })}. Dobrze sprawdza się krótka fraza z niepowiązanych słów.`,
      confirm: "Powtórz hasło",
      submit: "Utwórz konto i zaloguj się",
      busy: "Tworzenie konta",
    },
    validation: {
      enterUsername: "Wpisz nazwę użytkownika.",
      enterPassword: "Wpisz hasło.",
      chooseUsername: "Wybierz nazwę użytkownika.",
      atMost: (n) =>
        `Użyj najwyżej ${plural.pl(n, { one: "# znaku", few: "# znaków", many: "# znaków" })}.`,
      atLeast: (n) =>
        `Użyj co najmniej ${plural.pl(n, { one: "# znaku", few: "# znaków", many: "# znaków" })}.`,
      noSpaces: "Bez spacji, proszę.",
      mismatch: "Hasła się nie zgadzają.",
    },
    refusal: {
      appNotApproved: (org) =>
        `Organizacja ${org} nie zatwierdziła tej aplikacji. Poproś właściciela organizacji o zatwierdzenie aplikacji OAuth ExactDocs w ustawieniach GitHuba.`,
      ssoRequired: (org) =>
        `Autoryzuj SSO dla ${org}. Zatwierdź aplikację OAuth ExactDocs dla swojej organizacji w ustawieniach GitHuba, a potem spróbuj ponownie.`,
      orgDenied: (org) =>
        `Organizacja ${org} odmówiła dostępu. Poproś właściciela organizacji o sprawdzenie uprawnień aplikacji OAuth ExactDocs.`,
      teamRequired:
        "Nie należysz do żadnego dozwolonego zespołu. Poproś właściciela organizacji o dodanie Cię do zespołu z dostępem do tego serwera.",
      orgRequired:
        "Nie należysz do żadnej dozwolonej organizacji. Poproś właściciela organizacji o sprawdzenie Twojego członkostwa.",
      revoked:
        "Dostawca tożsamości cofnął to logowanie. Zaloguj się ponownie, aby przyznać dostęp.",
      notAllowed:
        "Dostawca tożsamości Cię zalogował, ale nie należysz do grupy z dostępem do tego serwera. Poproś administratora o dodanie Cię.",
      disabled: "Twoje konto jest wyłączone. Poproś administratora o jego włączenie.",
      usernameTaken:
        "Nie udało się utworzyć dla Ciebie konta: Twoja nazwa użytkownika jest zajęta. Poproś administratora o pomoc.",
      providerDown:
        "Dostawca tożsamości jest teraz nieosiągalny. Spróbuj ponownie za chwilę albo zaloguj się hasłem.",
      cancelled: "Dostawca tożsamości Cię nie zalogował. Spróbuj ponownie.",
      failed: "Nie udało się dokończyć logowania. Zacznij je od nowa na tej stronie.",
      notLinked:
        "Ta tożsamość nie jest powiązana z żadnym kontem na tym serwerze. Zaloguj się w inny sposób, a potem powiąż ją w zakładce Konto, Logowanie.",
    },
    errors: {
      adminCreated: "Konto administratora zostało utworzone, ale logowanie się nie powiodło.",
      signIn: "Zaloguj się",
      unreachable: "Brak połączenia z serwerem. Sprawdź połączenie i spróbuj ponownie.",
      invalidCredentials: "Nazwa użytkownika i hasło nie pasują do siebie.",
      waitLittle: "Odczekaj chwilę i spróbuj ponownie.",
      tryAgainIn: (seconds) =>
        `Spróbuj ponownie za ${plural.pl(seconds, { one: "# sekundę", few: "# sekundy", many: "# sekund" })}.`,
      tooMany: (when) => `Zbyt wiele nieudanych logowań. ${when}`,
      alreadySetUp: "Ten serwer ma już administratora.",
      signInInstead: "Zaloguj się",
      setupRequired: "Ten serwer nie ma jeszcze administratora.",
      setItUp: "Skonfiguruj go",
      server: (status) => `Na serwerze coś poszło nie tak (${status}). Spróbuj ponownie za chwilę.`,
    },
    screens: {
      notFound: "Nie znaleziono strony",
      nothingHere: "Pod tym adresem nic nie ma.",
      backToLibraries: "Wróć do bibliotek",
      somethingWrong: "Coś poszło nie tak",
      cantReach: "Brak połączenia z serwerem",
      didntAnswer: "ExactDocs nie odpowiada. Sprawdź, czy działa, i spróbuj ponownie.",
      tryAgain: "Spróbuj ponownie",
      loading: "Wczytywanie ",
    },
    preferences: {
      browser: "Zapisane w tej przeglądarce. Zaloguj się, aby zachować je na swoim koncie.",
      saving: "Zapisywanie na Twoim koncie…",
      saved: "Zapisane na Twoim koncie, więc działają w każdej przeglądarce.",
      unavailable:
        "Zapisane w tej przeglądarce: ten serwer nie przechowuje jeszcze ustawień interfejsu.",
      error: "Nie udało się zapisać na koncie. Twoje wybory nadal działają w tej przeglądarce.",
    },
    password: {
      title: "Hasło",
      description:
        "Zmień hasło, którym się logujesz. Pozostałe sesje zostaną zakończone; ta pozostanie zalogowana, a Twoje tokeny API nadal będą działać.",
      current: "Obecne hasło",
      next: "Nowe hasło",
      confirm: "Powtórz nowe hasło",
      hint: (min, max) =>
        `Od ${min} do ${max} znaków. Dobrze sprawdza się krótka fraza z niepowiązanych słów.`,
      show: {
        current: "Pokaż obecne hasło",
        next: "Pokaż nowe hasło",
        confirm: "Pokaż powtórzone hasło",
      },
      hide: {
        current: "Ukryj obecne hasło",
        next: "Ukryj nowe hasło",
        confirm: "Ukryj powtórzone hasło",
      },
      submit: "Zmień hasło",
      busy: "Zmienianie hasła",
      changed: "Hasło zostało zmienione. Pozostałe sesje zostały wylogowane.",
      toast: "Hasło zmienione",
      toastHint: "Pozostałe sesje zostały wylogowane. Twoje tokeny API nadal działają.",
      enterCurrent: "Wpisz obecne hasło.",
      wait: {
        seconds: (n) =>
          `Spróbuj ponownie za ${plural.pl(n, { one: "# sekundę", few: "# sekundy", many: "# sekund" })}.`,
        minutes: (n) =>
          `Spróbuj ponownie za ${plural.pl(n, { one: "# minutę", few: "# minuty", many: "# minut" })}.`,
        hours: (n) =>
          `Spróbuj ponownie za ${plural.pl(n, { one: "# godzinę", few: "# godziny", many: "# godzin" })}.`,
      },
      errors: {
        wrongPassword: "To nie jest Twoje obecne hasło.",
        tooMany: (when) => `Zbyt wiele błędnych haseł. ${when}`,
        waitLittle: "Odczekaj chwilę i spróbuj ponownie.",
        external: "To konto loguje się przez dostawcę tożsamości, więc nie ma hasła do zmiany.",
        sessionEnded: "Twoja sesja się zakończyła.",
        signIn: "Zaloguj się ponownie",
        newRefused: (min, max) => `Serwer odrzucił to hasło. Użyj od ${min} do ${max} znaków.`,
      },
      none: {
        access: "Logujesz się przez Cloudflare Access, więc nie masz tu hasła ExactDocs do zmiany.",
        provider: (name) =>
          `Logujesz się przez ${name}, więc nie masz tu hasła ExactDocs do zmiany.`,
        providers:
          "Logujesz się przez dostawcę tożsamości, więc nie masz tu hasła ExactDocs do zmiany.",
      },
    },
    providers: {
      title: "Powiązani dostawcy logowania",
      description:
        "Powiąż inny sposób logowania z tym samym kontem. Nic poza tym się nie zmienia: Twoja rola i grupy zostają takie same.",
      loading: "Wczytywanie dostawców logowania",
      loadFailed: "Nie udało się wczytać dostawców logowania.",
      list: "Dostawcy logowania",
      linked: "Powiązano",
      linkedSince: (date) => `Powiązano · od ${date}`,
      origin: "Utworzono nim konto",
      notLinked: "Niepowiązany",
      notConfigured: "Ten serwer już go nie oferuje",
      link: (name) => `Powiąż konto ${name}`,
      unlink: "Odłącz",
      unlinkName: (name) => `Odłącz ${name}`,
      cannotUnlink: (name) =>
        `To Twój jedyny sposób logowania: konto utworzono przez ${name} i nie ma ono hasła, więc nie można go odłączyć.`,
      confirmTitle: (name) => `Odłączyć ${name}?`,
      confirmBody: (name) =>
        `Nie będzie już można logować się przez ${name}. Obecne sesje pozostaną zalogowane, a dostawcę można później powiązać ponownie.`,
      confirm: "Odłącz",
      pending: "Odłączanie",
      unlinkedToast: (name) => `Odłączono konto ${name}`,
      linkedToast: (name) => `Powiązano konto ${name}`,
      linkedToastHint: (name) => `Możesz teraz logować się przez ${name}.`,
      linkedGeneric: "Powiązano dostawcę logowania",
      linkErrors: {
        elsewhere:
          "Ta tożsamość jest już powiązana z innym kontem ExactDocs. Najpierw ją tam odłącz albo zaloguj się nią, aby użyć tamtego konta.",
        alreadyLinked:
          "To konto ma już tożsamość tego dostawcy. Najpierw ją odłącz, aby powiązać inną.",
        notAllowed:
          "Dostawca Cię zalogował, ale ta tożsamość nie należy do grupy z dostępem do tego serwera, więc nie została powiązana.",
        notLinked:
          "Nie udało się powiązać tej tożsamości z tym kontem. Zacznij od nowa na tej stronie.",
        cancelled:
          "Dostawca nie potwierdził powiązania, więc nic się nie zmieniło. Spróbuj ponownie.",
        sessionEnded: "Twoja sesja zakończyła się przed powiązaniem, więc nic się nie zmieniło.",
        signIn: "Zaloguj się ponownie",
        unavailable: "Dostawca jest teraz nieosiągalny. Spróbuj ponownie za chwilę.",
        failed:
          "Nie udało się dokończyć powiązania, więc nic się nie zmieniło. Zacznij je od nowa na tej stronie.",
      },
      errors: {
        unreachable: "Brak połączenia z serwerem. Sprawdź połączenie i spróbuj ponownie.",
        alreadyLinked: (name) => `Dostawca ${name} jest już powiązany z tym kontem.`,
        unknown: (name) => `Ten serwer nie oferuje już logowania przez ${name}.`,
        unavailable: (name) =>
          `Dostawca ${name} jest teraz nieosiągalny. Spróbuj ponownie za chwilę.`,
        notLinked: (name) => `Dostawca ${name} nie był już powiązany.`,
        lastMethod: (name) =>
          `Logowanie przez ${name} to Twój jedyny sposób logowania, więc nie można go odłączyć.`,
        sessionEnded: "Twoja sesja się zakończyła.",
        signIn: "Zaloguj się ponownie",
        server: (status) =>
          `Na serwerze coś poszło nie tak (${status}). Spróbuj ponownie za chwilę.`,
      },
    },
    leaderboard: {
      label: "Pokazuj mnie w rankingu",
      description:
        "Pozwala osobom na tym serwerze zobaczyć Twoją nazwę użytkownika i liczbę przeczytanych dokumentów, wyszukiwań i pytań. Widać tylko liczby, nigdy to, co czytasz lub czego szukasz.",
      on: "Ranking osób jest włączony.",
      off: "Ranking osób jest wyłączony na tym serwerze, więc nikt nie jest pokazywany z nazwy. Twój wybór zostanie zachowany na czas, gdy operator go włączy.",
      unavailable:
        "Nie udało się wczytać wyboru zapisanego na Twoim koncie, więc nie można go teraz zmienić.",
    },
  },
);

/** A role's name in the UI language; an unknown role shows as the server sent it. */
export function roleName(roles: Record<string, string>, role: string | undefined): string {
  if (!role) return "";
  return roles[role] ?? role;
}
