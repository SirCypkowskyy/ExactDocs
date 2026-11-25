import { z } from "zod";

/** Feature flags read from the environment (every value is a string). */
const TRUE = ["true", "1", "yes", "on"];
const SPELLINGS = ["true", "1", "yes", "on", "false", "0", "no", "off"] as const;

const flag = z
  .string()
  .default("false")
  .transform((value) => value.toLowerCase())
  .pipe(z.enum(SPELLINGS))
  .transform((value) => TRUE.includes(value));

export const Flags = z.object({ DEBUG: flag, CACHE: flag });
