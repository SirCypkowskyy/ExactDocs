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
import { badge } from "../src/badge.ts";

const client = track(new QueryClient({ defaultOptions: { queries: { retry: false } } }));

test("a query without data is waiting", () => {
  const observer = new QueryObserver(client, { queryKey: ["never"], queryFn: () => new Promise<number>(() => {}) });
  assert.equal(badge(observer.getCurrentResult()), "waiting");
});

test("a query that succeeded is ok", async () => {
  await client.prefetchQuery({ queryKey: ["one"], queryFn: async () => 1 });
  const observer = new QueryObserver(client, { queryKey: ["one"], queryFn: async () => 1 });
  assert.equal(badge(observer.getCurrentResult()), "ok");
});

test("a query that failed has failed", async () => {
  const fail = async (): Promise<number> => {
    throw new Error("down");
  };
  await client.prefetchQuery({ queryKey: ["down"], queryFn: fail });
  const observer = new QueryObserver(client, { queryKey: ["down"], queryFn: fail });
  assert.equal(badge(observer.getCurrentResult()), "failed");
});
