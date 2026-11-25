import { z } from "zod";

/** A webhook delivery: its type and, for some types, a payload. */
export const Envelope = z.object({
  type: z.string().min(1),
  payload: z.unknown().optional(),
});

/** Validate a delivery, throwing on an invalid one. */
export function parseEnvelope(input: unknown): z.infer<typeof Envelope> {
  return Envelope.parse(input);
}
