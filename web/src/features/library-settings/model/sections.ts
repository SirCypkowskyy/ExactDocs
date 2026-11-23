/**
 * The settings page's sections, in order: [heading id, the id its form reports unsaved edits
 * under, which is also its label's key].
 */
export const SECTIONS = [
  ["details-heading", "details"],
  ["paths-heading", "paths"],
  ["versions-heading", "versions"],
  ["ai-heading", "ai"],
  ["sync-heading", "sync"],
  ["sharing-heading", "sharing"],
  ["danger-heading", "danger"],
] as const;

/** A section by the id its form reports unsaved edits under. */
export type SectionId = (typeof SECTIONS)[number][1];
