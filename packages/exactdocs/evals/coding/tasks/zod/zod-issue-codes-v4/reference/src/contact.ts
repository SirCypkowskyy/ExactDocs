import { z } from "zod";

/** A contact form. */
export const Contact = z.object({
  name: z.string().min(1),
  email: z.email(),
});

/** Each problem of an input, as `<field>: <kind>` (missing, empty, bad-email, wrong-type). */
export function summarize(input: unknown): string[] {
  const result = Contact.safeParse(input);
  if (result.success) return [];
  const given = typeof input === "object" && input !== null ? input : {};
  return result.error.issues.map((issue) => {
    const field = issue.path.join(".");
    if (!(field in given)) return `${field}: missing`;
    if (issue.code === "too_small") return `${field}: empty`;
    if (issue.code === "invalid_format" && issue.format === "email") return `${field}: bad-email`;
    return `${field}: wrong-type`;
  });
}
