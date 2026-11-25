import { z } from "zod";

/** A sign-up form. */
export const SignUp = z.object({
  username: z.string({
    required_error: "Username is required",
    invalid_type_error: "Username must be text",
  }),
  age: z.number(),
});

/** Each problem of an input, as `<field>: <message>`. */
export function problems(input: unknown): string[] {
  const result = SignUp.safeParse(input);
  return result.success ? [] : result.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`);
}
