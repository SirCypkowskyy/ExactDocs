import { z } from "zod";

/** A sign-up form. */
export const SignUp = z.object({
  username: z.string({
    error: (issue) => (issue.input === undefined ? "Username is required" : "Username must be text"),
  }),
  age: z.number(),
});

/** Each problem of an input, as `<field>: <message>`. */
export function problems(input: unknown): string[] {
  const result = SignUp.safeParse(input);
  return result.success ? [] : result.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`);
}
