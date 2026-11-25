import { z } from "zod";

/** Feature flags read from the environment (every value is a string). */
export const Flags = z.object({
  DEBUG: z.stringbool().default(false),
  CACHE: z.stringbool().default(false),
});
