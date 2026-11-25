import { z } from "zod";

/** An event as the API sends it: `at` is an ISO 8601 date-time string. */
export type WireEvent = { name: string; at: string };
/** An event as the app uses it: `at` is a Date. */
export type AppEvent = { name: string; at: Date };

const Wire = z.object({ name: z.string(), at: z.iso.datetime({ offset: true }) });

/** Validate an event from the API and give `at` as a Date. */
export function decodeEvent(wire: unknown): AppEvent {
  const event = Wire.parse(wire);
  return { name: event.name, at: new Date(event.at) };
}

/** Give an event back in its wire form. */
export function encodeEvent(event: AppEvent): WireEvent {
  return Wire.parse({ name: event.name, at: event.at.toISOString() });
}
