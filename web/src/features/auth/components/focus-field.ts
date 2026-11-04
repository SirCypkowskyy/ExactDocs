export function focusField(id: string, options?: { select?: boolean }) {
  const el = document.getElementById(id);
  el?.focus();
  if (options?.select && el instanceof HTMLInputElement) el.select();
}
