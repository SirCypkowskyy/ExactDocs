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
import { feedOptions, type Page } from "../src/feed.ts";

function feed() {
  const calls: unknown[] = [];
  const fetchPage = async (page: number): Promise<Page> => {
    calls.push(page);
    return { items: [`item ${page}`], next: page < 3 ? page + 1 : null };
  };
  return { calls, fetchPage };
}

test("the first page is page 1", async () => {
  const { calls, fetchPage } = feed();
  const client = track(new QueryClient());
  const data = await client.fetchInfiniteQuery(feedOptions(fetchPage) as never);
  assert.deepEqual(calls, [1]);
  assert.deepEqual((data as { pages: Page[] }).pages.map((p) => p.items), [["item 1"]]);
});

test("next pages follow `next` until it is null", async () => {
  const { calls, fetchPage } = feed();
  const client = track(new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } }));
  await client.fetchInfiniteQuery(feedOptions(fetchPage) as never);
  const observer = new InfiniteQueryObserver(client, feedOptions(fetchPage) as never);
  const unsubscribe = observer.subscribe(() => {});
  await observer.fetchNextPage();
  await observer.fetchNextPage();
  assert.deepEqual(calls, [1, 2, 3]);
  assert.equal(observer.getCurrentResult().hasNextPage, false);
  unsubscribe();
});
