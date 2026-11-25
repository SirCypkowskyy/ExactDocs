import { z } from "zod";

/** A server's network settings, read from a config file. */
export const ServerConfig = z.object({
  name: z.string(),
  // TODO: host and port
});
export type ServerConfig = z.infer<typeof ServerConfig>;
