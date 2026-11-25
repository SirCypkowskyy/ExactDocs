import { z } from "zod";

/** A contact form. */
export const Contact = z.object({
  name: z.string().min(1),
  email: z.email(),
});

/** Each problem of an input, as `<field>: <kind>` (missing, empty, bad-email, wrong-type). */
export function summarize(input: unknown): string[] {
  throw new Error("not implemented");
}
