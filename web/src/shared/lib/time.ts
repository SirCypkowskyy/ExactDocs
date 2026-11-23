import { currentLanguage, defineMessages, type Language } from "./i18n";

/*
 * Dates and times in the language the UI speaks (English or Polish), whatever the browser's
 * locale. Pass the language from `useLanguage()` so a component re-renders when it changes; it
 * defaults to the current one for code outside React.
 */

const messages = defineMessages({ justNow: "just now" }, { justNow: "przed chwilą" });

type Formats = {
  relative: Intl.RelativeTimeFormat;
  sameYear: Intl.DateTimeFormat;
  otherYear: Intl.DateTimeFormat;
  withZone: Intl.DateTimeFormat;
};

const cache = new Map<Language, Formats>();

function formats(language: Language): Formats {
  let found = cache.get(language);
  if (!found) {
    found = {
      relative: new Intl.RelativeTimeFormat(language, { numeric: "auto" }),
      sameYear: new Intl.DateTimeFormat(language, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }),
      otherYear: new Intl.DateTimeFormat(language, { dateStyle: "medium", timeStyle: "short" }),
      withZone: new Intl.DateTimeFormat(language, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        timeZoneName: "short",
      }),
    };
    cache.set(language, found);
  }
  return found;
}

/**
 * "3 days ago", "yesterday", "just now" ("3 dni temu", "wczoraj", "przed chwilą"). Floors, so
 * 59.6 minutes is minutes and 360 days is months; days up to 60, so a stale library never reads
 * as "last month". Never "in 3 minutes".
 */
export function relativeTime(
  iso: string,
  now: number,
  language: Language = currentLanguage(),
): string {
  const s = Math.max(0, (now - Date.parse(iso)) / 1000);
  if (s < 45) return messages[language].justNow;
  const { relative } = formats(language);
  const minutes = Math.max(1, Math.floor(s / 60));
  if (minutes < 60) return relative.format(-minutes, "minute");
  const hours = Math.floor(s / 3600);
  if (hours < 24) return relative.format(-hours, "hour");
  const days = Math.floor(s / 86_400);
  if (days <= 60) return relative.format(-days, "day");
  if (days < 365) return relative.format(-Math.min(11, Math.floor(days / 30)), "month");
  return relative.format(-Math.floor(days / 365), "year");
}

/** "Nov 4, 9:00 AM" ("4 lis, 09:00") this year, with the year before; one line. */
export function absoluteTime(iso: string, language: Language = currentLanguage()): string {
  const date = new Date(iso);
  const same = date.getFullYear() === new Date().getFullYear();
  const { sameYear, otherYear } = formats(language);
  return (same ? sameYear : otherYear).format(date);
}

/** For tooltips: adds the time zone, which the browser picked. */
export function absoluteTimeWithZone(iso: string, language: Language = currentLanguage()): string {
  return formats(language).withZone.format(new Date(iso));
}
