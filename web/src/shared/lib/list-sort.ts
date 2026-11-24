/** A `sort` value from the URL (a field, `-` in front for descending), kept only when the API knows the field. */
export function pickSort(value: unknown, fields: readonly string[]): string | undefined {
  if (typeof value !== "string") return undefined;
  return fields.includes(value.replace(/^-/, "")) ? value : undefined;
}

/** Free text from the URL, trimmed and capped at what the API accepts. */
export const textParam = (value: unknown): string | undefined =>
  (typeof value === "string" ? value.trim().slice(0, 256) : "") || undefined;
