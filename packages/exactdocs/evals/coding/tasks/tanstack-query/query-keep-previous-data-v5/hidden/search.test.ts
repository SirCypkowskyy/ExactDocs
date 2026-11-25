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
import { searchOptions } from "../src/search.ts";

test("the previous results stay until the new ones arrive", async () => {
  const client = track(new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  let finish: (results: string[]) => void = () => {};
  const search = (term: string) =>
    term === "a" ? Promise.resolve(["apple"]) : new Promise<string[]>((resolve) => (finish = resolve));
  const observer = new QueryObserver(client, searchOptions(search, "a") as never);
  const unsubscribe = observer.subscribe(() => {});
  await waitFor(() => observer.getCurrentResult().status === "success");
  observer.setOptions(searchOptions(search, "b") as never);
  await sleep(10);
  const meanwhile = observer.getCurrentResult() as { data?: unknown; isPlaceholderData?: boolean; isPreviousData?: boolean };
  assert.deepEqual(meanwhile.data, ["apple"]);
  assert.ok(meanwhile.isPlaceholderData || meanwhile.isPreviousData);
  finish(["banana"]);
  await waitFor(() => JSON.stringify(observer.getCurrentResult().data) === '["banana"]');
  unsubscribe();
});
