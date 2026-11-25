import { test, after } from "node:test";
import assert from "node:assert/strict";
import { QueryClient, QueryObserver, InfiniteQueryObserver } from "@tanstack/query-core";

const clients: QueryClient[] = [];
after(() => clients.forEach((client) => client.clear()));
function track(client: QueryClient): QueryClient {
  clients.push(client);
  return client;
}
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitFor(check: () => boolean, ms = 2000): Promise<void> {
  const until = Date.now() + ms;
  while (!check()) {
    if (Date.now() > until) throw new Error("timed out waiting");
    await sleep(5);
  }
}
void QueryObserver;
void InfiniteQueryObserver;
void waitFor;
import { onTodoAdded } from "../src/todos.ts";

test("only the todos queries are invalidated", async () => {
  const client = track(new QueryClient());
  client.setQueryData(["todos", "list"], ["a"]);
  client.setQueryData(["todos", 1], "a");
  client.setQueryData(["users"], ["ada"]);
  await onTodoAdded(client);
  assert.equal(client.getQueryState(["todos", "list"])?.isInvalidated, true);
  assert.equal(client.getQueryState(["todos", 1])?.isInvalidated, true);
  assert.equal(client.getQueryState(["users"])?.isInvalidated, false);
});
