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
import { userOptions, type User } from "../src/user.ts";

test("no fetch while there is no user ID", async () => {
  const client = track(new QueryClient());
  const asked: number[] = [];
  const fetchUser = async (id: number): Promise<User> => {
    asked.push(id);
    return { id, name: "Ada" };
  };
  const observer = new QueryObserver(client, userOptions(fetchUser, undefined) as never);
  const unsubscribe = observer.subscribe(() => {});
  await sleep(30);
  assert.deepEqual(asked, []);
  assert.equal(observer.getCurrentResult().status, "pending");
  assert.equal(observer.getCurrentResult().fetchStatus, "idle");
  observer.setOptions(userOptions(fetchUser, 7) as never);
  await waitFor(() => observer.getCurrentResult().status === "success");
  assert.deepEqual(asked, [7]);
  assert.deepEqual(observer.getCurrentResult().data, { id: 7, name: "Ada" });
  unsubscribe();
});
