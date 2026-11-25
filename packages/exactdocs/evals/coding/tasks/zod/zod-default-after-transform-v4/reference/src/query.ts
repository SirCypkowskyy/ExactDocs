import { z } from "zod";

/** The query string of the list endpoint. */
export const ListQuery = z.object({
  search: z.string().optional(),
  pageSize: z.string().regex(/^\d+$/).transform(Number).default(20),
});
