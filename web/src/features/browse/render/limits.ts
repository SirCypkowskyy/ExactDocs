/** A block longer than this is shown plain: highlighting runs on the main thread. */
export const MAX_BLOCK = 50_000;
/** Total characters highlighted per article; blocks past it stay plain. */
export const MAX_TOTAL = 200_000;

/** What an article may still spend on highlighting. */
export function createBudget(total = MAX_TOTAL) {
  let left = total;
  return {
    /** True (and spends it) when a block of `size` characters may be highlighted. */
    take(size: number): boolean {
      if (size > MAX_BLOCK || size > left) return false;
      left -= size;
      return true;
    },
  };
}
export type Budget = ReturnType<typeof createBudget>;

const idle = () =>
  new Promise<void>((resolve) =>
    typeof requestIdleCallback === "function"
      ? requestIdleCallback(() => resolve(), { timeout: 500 })
      : setTimeout(resolve, 0),
  );

let tail: Promise<unknown> = Promise.resolve();

/** Run `task` when the browser is idle and nothing else of this kind is running: one block at a time. */
export function inTurn<T>(task: () => Promise<T>): Promise<T> {
  const run = tail.then(idle).then(task);
  tail = run.catch(() => {});
  return run;
}
