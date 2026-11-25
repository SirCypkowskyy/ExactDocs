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
import { createClient } from "../src/client.ts";

test("unused data is removed from the cache after 100 ms", async () => {
  const client = track(createClient());
  await client.prefetchQuery({ queryKey: ["a"], queryFn: async () => 1 });
  assert.equal(client.getQueryData(["a"]), 1);
  await sleep(400);
  assert.equal(client.getQueryCache().find({ queryKey: ["a"] }), undefined);
});

test("data stays fresh for 30 seconds", async () => {
  const client = track(createClient());
  let calls = 0;
  const queryFn = async () => ++calls;
  await client.fetchQuery({ queryKey: ["b"], queryFn });
  await client.fetchQuery({ queryKey: ["b"], queryFn });
  assert.equal(calls, 1);
});
