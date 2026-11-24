import { currentLanguage, formatNumber, type Language } from "./i18n";

/*
 * Numbers with units, in the language the UI speaks. Intl does the words and the separators
 * ("12.4 kB", "12,4 kB"; "$3.10", "3,10 USD"), so nothing here is translated by hand.
 */

const BYTE_UNITS = ["byte", "kilobyte", "megabyte", "gigabyte", "terabyte"] as const;

/** 980 B, 12.4 kB, 3.1 MB: decimal units (1 kB = 1000 B), one decimal above a kilobyte. */
export function formatBytes(bytes: number, language: Language = currentLanguage()): string {
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1000 && unit < BYTE_UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  // Intl writes English bytes as a word ("900 byte"); a size reads "900 B" in both languages.
  if (unit === 0) return `${formatNumber(Math.round(value), language)} B`;
  return formatNumber(value, language, {
    style: "unit",
    unit: BYTE_UNITS[unit],
    unitDisplay: "short",
    maximumFractionDigits: unit === 0 ? 0 : 1,
  });
}

/** US dollars, as the AI budgets count them: two decimals, four below a cent so it is never "$0.00". */
export function formatMoney(usd: number, language: Language = currentLanguage()): string {
  const small = usd !== 0 && Math.abs(usd) < 0.01;
  return formatNumber(usd, language, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: small ? 4 : 2,
  });
}

/** A span of time, short: "45 s", "2 min", "1 h 5 min", "3 d 4 h" (Polish: "1 godz. 5 min"). */
export function formatDuration(ms: number, language: Language = currentLanguage()): string {
  const s = Math.max(0, Math.round(ms / 1000));
  const part = (value: number, unit: "second" | "minute" | "hour" | "day") =>
    formatNumber(value, language, { style: "unit", unit, unitDisplay: "short" });
  if (s < 60) return part(s, "second");
  const minutes = Math.floor(s / 60);
  if (minutes < 60) return part(minutes, "minute");
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const rest = minutes % 60;
    return rest ? `${part(hours, "hour")} ${part(rest, "minute")}` : part(hours, "hour");
  }
  const days = Math.floor(hours / 24);
  const rest = hours % 24;
  return rest ? `${part(days, "day")} ${part(rest, "hour")}` : part(days, "day");
}
