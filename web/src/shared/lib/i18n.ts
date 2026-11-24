import type { ReactNode } from "react";
import { type Language, readPreferences, resolveLanguage, usePreferences } from "./preferences";

/*
 * The UI speaks English and Polish (#486). Strings live next to the code that shows them: every
 * feature has a `messages.ts` (or `.tsx`, when a message carries markup) made with
 * `defineMessages(en, pl)`. English defines the shape; TypeScript rejects a Polish catalogue that
 * misses a key or changes a function's arguments, so nothing ships half-translated.
 *
 *   const t = useMessages(messages);
 *   <h1>{t.title}</h1>  <p>{t.count(libraries.length)}</p>
 *
 * A message is a string, or a function for anything with values in it (counts, names, markup).
 * Plurals go through `plural.en` / `plural.pl`: Polish has three forms (1 biblioteka,
 * 2 biblioteki, 5 bibliotek), so a message never builds a plural by adding an "s".
 * Text that comes from the server (error details, library content) stays as the server sent it.
 */

export type { Language };

/** Each language's name in itself: the switcher never translates them. */
export const LANGUAGE_NAMES: Readonly<Record<Language, string>> = {
  en: "English",
  pl: "Polski",
};

export const LANGUAGES: readonly Language[] = ["en", "pl"];

type Message = string | ((...args: never[]) => ReactNode);
/** A catalogue: messages, or groups of them. */
export type Messages = { readonly [key: string]: Message | Messages };

export type Catalog<M> = Readonly<Record<Language, M>>;

/** English first (it defines the keys and argument types), then Polish with the same shape. */
export function defineMessages<M extends Messages>(en: M, pl: NoInfer<M>): Catalog<M> {
  return { en, pl };
}

/** The language the UI shows now; re-renders when it changes. */
export function useLanguage(): Language {
  return usePreferences().language;
}

/** The catalogue in the language the UI shows now; re-renders when the language changes. */
export function useMessages<M>(catalog: Catalog<M>): M {
  return catalog[useLanguage()];
}

/** The language outside React (route `head`, a schema's error text built once per call). */
export function currentLanguage(): Language {
  return resolveLanguage(readPreferences().language);
}

/** The catalogue outside React, in the current language unless one is given. */
export function messagesFor<M>(catalog: Catalog<M>, language: Language = currentLanguage()): M {
  return catalog[language];
}

const numberFormats = new Map<string, Intl.NumberFormat>();

/** 1,234 in English, 1234 and 12 345 in Polish. */
export function formatNumber(
  value: number,
  language: Language = currentLanguage(),
  options?: Intl.NumberFormatOptions,
): string {
  const key = `${language}|${JSON.stringify(options ?? {})}`;
  let format = numberFormats.get(key);
  if (!format) {
    format = new Intl.NumberFormat(language, options);
    numberFormats.set(key, format);
  }
  return format.format(value);
}

const pluralRules = {
  en: new Intl.PluralRules("en"),
  pl: new Intl.PluralRules("pl"),
};

const fill = (form: string, count: number, language: Language) =>
  form.replaceAll("#", formatNumber(count, language));

/**
 * The right plural form, with `#` replaced by the formatted count:
 *   plural.en(n, { one: "# library", other: "# libraries" })
 *   plural.pl(n, { one: "# biblioteka", few: "# biblioteki", many: "# bibliotek" })
 * Polish `other` (fractions: 1,5 biblioteki) defaults to `few`.
 */
export const plural = {
  en(count: number, forms: { one: string; other: string }): string {
    const form = pluralRules.en.select(count) === "one" ? forms.one : forms.other;
    return fill(form, count, "en");
  },
  pl(count: number, forms: { one: string; few: string; many: string; other?: string }): string {
    const rule = pluralRules.pl.select(count);
    const form =
      rule === "one"
        ? forms.one
        : rule === "few"
          ? forms.few
          : rule === "many"
            ? forms.many
            : (forms.other ?? forms.few);
    return fill(form, count, "pl");
  },
};

/** Words every feature needs, so "Cancel" reads the same everywhere. */
export const common = defineMessages(
  {
    cancel: "Cancel",
    close: "Close",
    save: "Save",
    saving: "Saving…",
    delete: "Delete",
    remove: "Remove",
    edit: "Edit",
    copy: "Copy",
    copied: "Copied",
    retry: "Try again",
    loading: "Loading…",
    back: "Back",
    next: "Next",
    previous: "Previous",
    done: "Done",
    yes: "Yes",
    no: "No",
    none: "None",
    optional: "optional",
    search: "Search",
    clearSearch: "Clear search",
    showMore: "Show more",
    showLess: "Show less",
    somethingWentWrong: "Something went wrong",
  },
  {
    cancel: "Anuluj",
    close: "Zamknij",
    save: "Zapisz",
    saving: "Zapisywanie…",
    delete: "Usuń",
    remove: "Usuń",
    edit: "Edytuj",
    copy: "Kopiuj",
    copied: "Skopiowano",
    retry: "Spróbuj ponownie",
    loading: "Wczytywanie…",
    back: "Wstecz",
    next: "Dalej",
    previous: "Wstecz",
    done: "Gotowe",
    yes: "Tak",
    no: "Nie",
    none: "Brak",
    optional: "opcjonalnie",
    search: "Szukaj",
    clearSearch: "Wyczyść wyszukiwanie",
    showMore: "Pokaż więcej",
    showLess: "Pokaż mniej",
    somethingWentWrong: "Coś poszło nie tak",
  },
);
