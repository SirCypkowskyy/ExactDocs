import { currentLanguage, defineMessages, type Language } from "./i18n";

/*
 * Dates and times in the language the UI speaks (English or Polish), whatever the browser's
 * locale. Pass the language from `useLanguage()` so a component re-renders when it changes; it
 * defaults to the current one for code outside React.
 */

const messages = defineMessages(
  { justNow: "just now", inAMoment: "in a moment" },
  { justNow: "przed chwilą", inAMoment: "za chwilę" },
);

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
 * as "last month". Never "in 3 minutes": a time a little ahead (another clock) is "just now".
 *
 * With `future` it looks ahead instead (an expiry): "in 3 days", "tomorrow", "in a moment"
 * ("za 3 dni", "jutro", "za chwilę"), and a time already past is "in a moment".
 */
export function relativeTime(
  iso: string,
  now: number,
  language: Language = currentLanguage(),
  { future = false }: { future?: boolean } = {},
): string {
  const sign = future ? 1 : -1;
  const s = Math.max(0, (sign * (Date.parse(iso) - now)) / 1000);
  if (s < 45) return future ? messages[language].inAMoment : messages[language].justNow;
  const { relative } = formats(language);
  const minutes = Math.max(1, Math.floor(s / 60));
  if (minutes < 60) return relative.format(sign * minutes, "minute");
  const hours = Math.floor(s / 3600);
  if (hours < 24) return relative.format(sign * hours, "hour");
  const days = Math.floor(s / 86_400);
  if (days <= 60) return relative.format(sign * days, "day");
  if (days < 365) return relative.format(sign * Math.min(11, Math.floor(days / 30)), "month");
  return relative.format(sign * Math.floor(days / 365), "year");
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
