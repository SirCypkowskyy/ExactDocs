import { z } from "zod";

/** An event as the API sends it: `at` is an ISO 8601 date-time string. */
export type WireEvent = { name: string; at: string };
/** An event as the app uses it: `at` is a Date. */
export type AppEvent = { name: string; at: Date };

const isoDate = z.codec(z.iso.datetime({ offset: true }), z.date(), {
  decode: (text) => new Date(text),
  encode: (date) => date.toISOString(),
});
const Event = z.object({ name: z.string(), at: isoDate });

/** Validate an event from the API and give `at` as a Date. */
export function decodeEvent(wire: unknown): AppEvent {
  return Event.parse(wire);
}

/** Give an event back in its wire form. */
export function encodeEvent(event: AppEvent): WireEvent {
  return z.encode(Event, event);
}
