const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const sameYear = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const otherYear = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});
const withZone = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});

/**
 * "3 days ago", "yesterday", "just now". Floors, so 59.6 minutes is minutes and 360 days is
 * months; days up to 60, so a stale library never reads as "last month". Never "in 3 minutes".
 */
export function relativeTime(iso: string, now: number): string {
  const s = Math.max(0, (now - Date.parse(iso)) / 1000);
  if (s < 45) return "just now";
  const minutes = Math.max(1, Math.floor(s / 60));
  if (minutes < 60) return relative.format(-minutes, "minute");
  const hours = Math.floor(s / 3600);
  if (hours < 24) return relative.format(-hours, "hour");
  const days = Math.floor(s / 86_400);
  if (days <= 60) return relative.format(-days, "day");
  if (days < 365) return relative.format(-Math.min(11, Math.floor(days / 30)), "month");
  return relative.format(-Math.floor(days / 365), "year");
}

/** "Nov 4, 9:00 AM" this year, with the year before; one line. */
export function absoluteTime(iso: string): string {
  const date = new Date(iso);
  const same = date.getFullYear() === new Date().getFullYear();
  return (same ? sameYear : otherYear).format(date);
}

/** For tooltips: adds the time zone, which the browser picked. */
export function absoluteTimeWithZone(iso: string): string {
  return withZone.format(new Date(iso));
}
