import { z } from "zod";

/** A server's network settings, read from a config file. */
export const ServerConfig = z.object({
  name: z.string(),
  host: z.ipv4(),
  port: z.int().min(1).max(65535),
});
export type ServerConfig = z.infer<typeof ServerConfig>;

/** Validate a config, throwing on an invalid one. */
export function parseConfig(input: unknown): ServerConfig {
  return ServerConfig.parse(input);
}
