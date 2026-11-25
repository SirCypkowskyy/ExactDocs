import { QueryClient } from "@tanstack/query-core";

/** After a todo was added: every query of todos is stale, the active ones refetch. */
export async function onTodoAdded(client: QueryClient): Promise<void> {
  await client.invalidateQueries({ queryKey: ["todos"] });
}
