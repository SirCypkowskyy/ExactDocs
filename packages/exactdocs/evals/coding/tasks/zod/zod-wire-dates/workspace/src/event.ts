import { z } from "zod";

/** An event as the API sends it: `at` is an ISO 8601 date-time string. */
export type WireEvent = { name: string; at: string };
/** An event as the app uses it: `at` is a Date. */
export type AppEvent = { name: string; at: Date };
