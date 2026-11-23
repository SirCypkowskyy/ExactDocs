import type { ReactNode } from "react";
import { defineMessages, formatNumber, plural } from "@/shared/lib/i18n";

/** Strings of a running job: the import screen, a job's line, cancelling it, the files it skipped. */

/**
 * What one kind of job says about itself. An import counts files; re-processing, re-chunking and
 * re-tagging a library count versions. `skipped` is a label ("12", "1000+"), `total` null when the
 * job has not counted yet.
 */
type JobKindMessages = {
  queued: string;
  running: string;
  finished: (done: number, skipped: string) => string;
  failed: (error: string | null) => string;
  cancelled: string;
  meter: (id: string) => string;
  progress: (done: number, total: number) => string;
  starting: string;
  doneCount: (done: number, skipped: string) => string;
  cancelledAfter: (by: string | null, done: number, total: number | null) => string;
  stoppedAfter: (done: number, total: number | null) => string;
  triedAll: (total: number) => string;
};

function enKind(w: {
  unit: "file" | "version";
  /** “Import”, “Re-processing”: the start of each phase sentence. */
  noun: string;
  /** “Importing.”: the sentence while it runs. */
  running: string;
  /** “imported”: what a counted item is once done. */
  done: string;
}): JobKindMessages {
  const units = (n: number) => plural.en(n, { one: w.unit, other: `${w.unit}s` });
  const after = (done: number, total: number | null) =>
    `${done}${total !== null ? ` of ${total}` : ""} ${units(total ?? done)}`;
  return {
    queued: `${w.noun} queued.`,
    running: w.running,
    finished: (done, skipped) =>
      w.unit === "file"
        ? `${w.noun} finished. ${done} ${units(done)} ${w.done}, ${skipped} skipped.`
        : `${w.noun} finished. ${done} ${units(done)} ${w.done}.`,
    failed: (error) => `${w.noun} failed. ${error ?? ""}`.trim(),
    cancelled: `${w.noun} cancelled.`,
    meter: (id) => `${w.noun} progress for ${id}`,
    progress: (done, total) => `${done} of ${total} ${units(total)}`,
    starting: w.unit === "file" ? "Reading the repository" : "Starting",
    doneCount: (done, skipped) =>
      `${done} ${units(done)} ${w.done}${w.unit === "file" && skipped !== "0" ? `, ${skipped} skipped` : ""}`,
    cancelledAfter: (by, done, total) =>
      `Cancelled${by ? ` by ${by}` : ""} after ${after(done, total)}`,
    stoppedAfter: (done, total) => `Stopped after ${after(done, total)}`,
    triedAll: (total) =>
      `Failed: all ${total} ${units(total)} tried, not every one could be ${w.done}`,
  };
}

const plFiles = {
  /** Mianownik i biernik: 1 plik, 2 pliki, 5 plików. */
  acc: (n: number) => plural.pl(n, { one: "# plik", few: "# pliki", many: "# plików" }),
  /** Dopełniacz: z 1 pliku, z 2 plików. */
  gen: (n: number) => plural.pl(n, { one: "# pliku", few: "# plików", many: "# plików" }),
};
const plVersions = {
  acc: (n: number) => plural.pl(n, { one: "# wersję", few: "# wersje", many: "# wersji" }),
  gen: (n: number) => plural.pl(n, { one: "# wersji", few: "# wersji", many: "# wersji" }),
};

function plKind(w: {
  unit: "file" | "version";
  queued: string;
  running: string;
  /** „Import zakończony.” */
  finished: string;
  /** „Import nieudany.” */
  failed: string;
  cancelled: string;
  /** „Postęp importu” */
  meter: string;
  /** „Zaimportowano”: przed liczbą ukończonych. */
  did: string;
  /** „zaimportować”: czego nie udało się zrobić z każdą wersją. */
  infinitive: string;
}): JobKindMessages {
  const units = w.unit === "file" ? plFiles : plVersions;
  const after = (done: number, total: number | null) =>
    total !== null ? `${formatNumber(done, "pl")} z ${units.gen(total)}` : units.gen(done);
  const doneCount = (done: number, skipped: string) =>
    `${w.did} ${units.acc(done)}${w.unit === "file" && skipped !== "0" ? `, pominięto ${skipped}` : ""}`;
  return {
    queued: w.queued,
    running: w.running,
    finished: (done, skipped) =>
      w.unit === "file"
        ? `${w.finished} ${w.did} ${units.acc(done)}, pominięto ${skipped}.`
        : `${w.finished} ${w.did} ${units.acc(done)}.`,
    failed: (error) => `${w.failed} ${error ?? ""}`.trim(),
    cancelled: w.cancelled,
    meter: (id) => `${w.meter} ${id}`,
    progress: (done, total) => `${formatNumber(done, "pl")} z ${units.gen(total)}`,
    starting: w.unit === "file" ? "Odczytywanie repozytorium" : "Uruchamianie",
    doneCount,
    cancelledAfter: (by, done, total) =>
      `Anulowano${by ? ` przez użytkownika ${by}` : ""} po przetworzeniu ${after(done, total)}`,
    stoppedAfter: (done, total) => `Zatrzymano po przetworzeniu ${after(done, total)}`,
    triedAll: (total) =>
      `Błąd: próbowano wszystkich ${units.gen(total)}, ${w.unit === "file" ? "nie każdy" : "nie każdą"} udało się ${w.infinitive}`,
  };
}

export const progressMessages = defineMessages(
  {
    kinds: {
      import: enKind({ unit: "file", noun: "Import", running: "Importing.", done: "imported" }),
      reprocess: enKind({
        unit: "version",
        noun: "Re-processing",
        running: "Re-processing.",
        done: "re-processed",
      }),
      rechunk: enKind({
        unit: "version",
        noun: "Re-chunking",
        running: "Re-chunking.",
        done: "re-chunked",
      }),
      retag: enKind({
        unit: "version",
        noun: "Re-tagging",
        running: "Re-tagging.",
        done: "re-tagged",
      }),
    },
    waitingForWorker: "Waiting for a free worker",
    valueText: (done: number, total: number) => `${done} of ${total}`,
    heading: {
      failed: "Import failed",
      cancelled: "Import cancelled",
      imported: "Imported",
      importing: "Importing",
    },
    commit: " commit",
    gone: "We can't find this import any more, so its progress can't be shown. The library list shows where things stand.",
    lostContact: "Lost contact, retrying…",
    lineGone: (label: string) => `Progress for ${label} is gone.`,
    cancelLabel: (id: string) => `the import of ${id}`,
    libraryFailed: (settings: (text: string) => ReactNode) => (
      <>
        The library was created, but this version did not finish importing, so it has no articles
        yet. Fix the cause below, then sync it again from the library's {settings("settings page")}.
      </>
    ),
    versionFailed:
      "This version did not finish importing, so it was not added. Fix the cause below, then add it again.",
    serverDetails: "Details from the server",
    noReason: "No reason was recorded.",
    addAnother: "Add another",
    backToLibraries: "Back to libraries",
    canLeave:
      "You can leave this page. The import keeps running, and the library list shows how it went.",
    toast: {
      imported: (what: string) => `Imported ${what}`,
      importedDetail: (done: number, skipped: string) =>
        `${done} ${plural.en(done, { one: "file", other: "files" })} imported${skipped !== "0" ? `, ${skipped} skipped` : ""}.`,
      failed: (what: string) => `Import of ${what} failed`,
    },
    cancel: {
      cancelling: "Cancelling after the current step…",
      ask: (label: string) => `Cancel ${label}?`,
      willNotStart: "It has not started, so it never will.",
      stopsAfterStep: "It stops after the current step and keeps what it finished.",
      confirm: "Yes, cancel",
      keep: "Keep it",
      offline: "Can't reach the server. Try again.",
      forbidden: "Your role on this library doesn't allow cancelling jobs.",
      ended: "The job ended before it could be cancelled.",
      server: (status: number) => `Something went wrong on the server (${status}). Try again.`,
    },
    skipped: {
      title: "Skipped files",
      leftOut: "These were left out of the version. The rest was imported.",
      firstOnly: (n: number) =>
        `Showing the first ${n} skipped files. More were skipped for the same kinds of reasons.`,
      notes: "Imported with a note",
      columns: { path: "Path", problem: "Problem", result: "Result" },
      results: { skipped: "Skipped" },
      find: "Find a file",
      findPlaceholder: "Path or reason",
      noMatch: "No file matches",
      copyPath: "Copy path",
      pathCopied: "Copied the path.",
    },
  },
  {
    kinds: {
      import: plKind({
        unit: "file",
        queued: "Import w kolejce.",
        running: "Trwa import.",
        finished: "Import zakończony.",
        failed: "Import nieudany.",
        cancelled: "Import anulowany.",
        meter: "Postęp importu",
        did: "Zaimportowano",
        infinitive: "zaimportować",
      }),
      reprocess: plKind({
        unit: "version",
        queued: "Ponowne przetwarzanie w kolejce.",
        running: "Trwa ponowne przetwarzanie.",
        finished: "Ponowne przetwarzanie zakończone.",
        failed: "Ponowne przetwarzanie nieudane.",
        cancelled: "Ponowne przetwarzanie anulowane.",
        meter: "Postęp ponownego przetwarzania",
        did: "Ponownie przetworzono",
        infinitive: "ponownie przetworzyć",
      }),
      rechunk: plKind({
        unit: "version",
        queued: "Ponowny podział na fragmenty w kolejce.",
        running: "Trwa ponowny podział na fragmenty.",
        finished: "Ponowny podział na fragmenty zakończony.",
        failed: "Ponowny podział na fragmenty nieudany.",
        cancelled: "Ponowny podział na fragmenty anulowany.",
        meter: "Postęp ponownego podziału na fragmenty",
        did: "Ponownie podzielono na fragmenty",
        infinitive: "ponownie podzielić na fragmenty",
      }),
      retag: plKind({
        unit: "version",
        queued: "Ponowne tagowanie w kolejce.",
        running: "Trwa ponowne tagowanie.",
        finished: "Ponowne tagowanie zakończone.",
        failed: "Ponowne tagowanie nieudane.",
        cancelled: "Ponowne tagowanie anulowane.",
        meter: "Postęp ponownego tagowania",
        did: "Ponownie otagowano",
        infinitive: "ponownie otagować",
      }),
    },
    waitingForWorker: "Czeka na wolny proces roboczy",
    valueText: (done, total) => `${formatNumber(done, "pl")} z ${formatNumber(total, "pl")}`,
    heading: {
      failed: "Nieudany import",
      cancelled: "Anulowany import",
      imported: "Zaimportowano",
      importing: "Importowanie",
    },
    commit: " commit",
    gone: "Nie można już znaleźć tego importu, więc nie da się pokazać jego postępu. Aktualny stan widać na liście bibliotek.",
    lostContact: "Utracono połączenie, ponawianie…",
    lineGone: (label) => `Postęp dla ${label} nie jest już dostępny.`,
    cancelLabel: (id) => `import ${id}`,
    libraryFailed: (settings) => (
      <>
        Biblioteka została utworzona, ale import tej wersji się nie zakończył, więc nie ma ona
        jeszcze artykułów. Usuń przyczynę opisaną poniżej, a potem ponownie zsynchronizuj bibliotekę
        na {settings("stronie ustawień")}.
      </>
    ),
    versionFailed:
      "Import tej wersji się nie zakończył, więc nie została dodana. Usuń przyczynę opisaną poniżej i dodaj ją ponownie.",
    serverDetails: "Szczegóły z serwera",
    noReason: "Nie zapisano przyczyny.",
    addAnother: "Dodaj kolejną",
    backToLibraries: "Wróć do bibliotek",
    canLeave:
      "Możesz opuścić tę stronę. Import będzie trwał dalej, a lista bibliotek pokaże jego wynik.",
    toast: {
      imported: (what) => `Zaimportowano ${what}`,
      importedDetail: (done, skipped) =>
        `Zaimportowane pliki: ${formatNumber(done, "pl")}${skipped !== "0" ? `, pominięte: ${skipped}` : ""}.`,
      failed: (what) => `Nie udało się zaimportować ${what}`,
    },
    cancel: {
      cancelling: "Anulowanie po bieżącym kroku…",
      ask: (label) => `Anulować ${label}?`,
      willNotStart: "Jeszcze się nie rozpoczęło, więc nie zostanie uruchomione.",
      stopsAfterStep: "Zatrzyma się po bieżącym kroku i zachowa to, co już ukończyło.",
      confirm: "Tak, anuluj",
      keep: "Zostaw",
      offline: "Nie można połączyć się z serwerem. Spróbuj ponownie.",
      forbidden: "Twoja rola w tej bibliotece nie pozwala anulować zadań.",
      ended: "Zadanie zakończyło się, zanim udało się je anulować.",
      server: (status) => `Wystąpił błąd na serwerze (${status}). Spróbuj ponownie.`,
    },
    skipped: {
      title: "Pominięte pliki",
      leftOut: "Te pliki pominięto w tej wersji. Pozostałe zaimportowano.",
      firstOnly: (n) =>
        `Wyświetlono ${plural.pl(n, {
          one: "pierwszy pominięty plik",
          few: "pierwsze # pominięte pliki",
          many: "pierwszych # pominiętych plików",
        })}. Więcej plików pominięto z podobnych powodów.`,
      notes: "Zaimportowane z uwagą",
      columns: { path: "Ścieżka", problem: "Problem", result: "Wynik" },
      results: { skipped: "Pominięty" },
      find: "Znajdź plik",
      findPlaceholder: "Ścieżka lub przyczyna",
      noMatch: "Żaden plik nie pasuje",
      copyPath: "Kopiuj ścieżkę",
      pathCopied: "Skopiowano ścieżkę.",
    },
  },
);

export type JobKindKey = keyof (typeof progressMessages)["en"]["kinds"];
