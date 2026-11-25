import { z } from "zod";

/** A user's editor settings. */
export const Settings = z.object({
  theme: z.enum(["light", "dark"]),
  editor: z.object({
    fontSize: z.number().int(),
    tabs: z.object({ size: z.number().int(), spaces: z.boolean() }),
  }),
});

/** Settings with every field optional at every level. */
export const SettingsPatch = z.deepPartial(Settings);
