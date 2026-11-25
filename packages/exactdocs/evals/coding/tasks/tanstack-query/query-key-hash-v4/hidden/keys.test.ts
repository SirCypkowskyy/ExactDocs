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
import { cacheIdOf } from "../src/keys.ts";

test("the order of an object's properties does not matter", () => {
  assert.equal(cacheIdOf(["todos", { page: 1, sort: "asc" }]), cacheIdOf(["todos", { sort: "asc", page: 1 }]));
  assert.notEqual(cacheIdOf(["todos", 1]), cacheIdOf(["todos", "1"]));
});

test("it is the cached query's hash", () => {
  const client = track(new QueryClient());
  const key = ["todos", { page: 2 }];
  client.setQueryData(key, ["a"]);
  const query = client.getQueryCache().getAll()[0];
  assert.equal(cacheIdOf(key), query.queryHash);
});
