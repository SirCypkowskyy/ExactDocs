import { z } from "zod";

/** Exchange rates by currency name, from a rates feed. */
export const Rates = z.record(z.number().positive());

/** Validate rates, throwing on invalid ones. */
export function parseRates(input: unknown): Record<string, number> {
  return Rates.parse(input);
}
