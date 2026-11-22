import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const FIXTURE_REPO_URL = process.env.FIXTURE_REPO_URL;
if (!FIXTURE_REPO_URL) throw new Error("FIXTURE_REPO_URL is not set: run the test through e2e/run.py");
const PASSWORD = "a long passphrase here";
const baseURL = process.env.EXACTDOCS_URL;

test("setup, add the fixture repository, browse an article, search a term", async ({ page }) => {
  // setup: a fresh instance sends every visitor to it
  await page.goto("/");
  await expect(page).toHaveURL(/\/setup$/);
  await page.getByLabel("Username").fill("ada");
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Repeat the password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account and sign in" }).click();
  await expect(page.getByRole("heading", { name: "Libraries" })).toBeVisible();

  // add the fixture repository over HTTP git
  await page.goto("/libraries/new");
  await page.getByLabel("Repository address").fill(FIXTURE_REPO_URL);
  await page.getByRole("button", { name: "Check repository" }).click();
  await expect(page.getByText("Found on a git server")).toBeVisible();
  await page.getByLabel("Version to import").selectOption({ label: "v1.4.0" });
  await page.getByRole("button", { name: "Add library" }).click();
  await expect(page.getByText(/^\d+ files imported/).first()).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: "shots/1-imported.png" });

  // the same repository again: the form says its library ID is taken and links to that library (#219)
  await page.goto("/libraries/new");
  await page.getByLabel("Repository address").fill(FIXTURE_REPO_URL);
  await page.getByRole("button", { name: "Check repository" }).click();
  await expect(
    page.getByText("A library with this repository's ID, /fixture/docs-repo, already exists."),
  ).toBeVisible();
  await page.getByRole("link", { name: "Open /fixture/docs-repo" }).click();
  await expect(page).toHaveURL(/\/libraries\/fixture\/docs-repo$/);
  await expect(
    page.getByRole("navigation", { name: "Breadcrumb" }).getByText("/fixture/docs-repo"),
  ).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  // browse: the Resilience article renders (markdown, highlighted code, table, callout)
  await page.goto("/libraries/fixture/docs-repo?version=v1.4.0");
  await page.getByRole("treeitem", { name: "docs", exact: true }).click();
  await page.getByRole("treeitem", { name: "guide", exact: true }).click();
  await page.getByRole("treeitem", { name: "Resilience" }).click();
  await expect(page).toHaveURL(/resilience\.md/);
  await expect(page.getByRole("heading", { name: "Resilience" }).first()).toBeVisible();
  await expect(page.locator(".doc-code")).toBeVisible();
  await expect(page.locator(".doc-table table")).toBeVisible();
  await expect(page.locator(".doc-callout")).toBeVisible();
  await page.screenshot({ path: "shots/2-article.png" });

  // search: the result opens its section
  // the header also holds the all-libraries box (#187): use the per-version one
  await page.getByRole("searchbox", { name: "Search v1.4.0" }).fill("retry_policy");
  await page.keyboard.press("Enter");
  const hit = page.locator("[data-result]").first();
  await expect(hit).toContainText("resilience.md");
  await page.screenshot({ path: "shots/3-search.png" });
  await hit.click();
  const section = page.locator("#doc-retry_policy");
  await expect(page).toHaveURL(/#retry_policy$/);
  await expect(section).toBeInViewport();
  await expect(section).toHaveClass(/doc-target/);
  await page.screenshot({ path: "shots/4-section.png" });
});

async function signIn(page: Page) {
  await page.goto("/sign-in");
  await page.getByLabel("Username").fill("ada");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Libraries" })).toBeVisible();
}

// #426: the main pages in both themes, screenshotted, with no axe violation (contrast included).
// Runs after the test above, in the same worker: it reads the library that test imported.
test("the main pages read in the light and the dark theme", async ({ browser }) => {
  const pages = [
    ["libraries", "/"],
    ["article", "/libraries/fixture/docs-repo?version=v1.4.0&path=docs%2Fguide%2Fresilience.md"],
    ["callouts", "/libraries/fixture/docs-repo?version=v1.4.0&path=docs%2Fguide%2Fcallouts.md"],
    ["search", "/libraries/fixture/docs-repo?version=v1.4.0&q=retry_policy"],
    ["settings", "/libraries/fixture/docs-repo/settings"],
    ["account", "/account"],
  ] as const;
  for (const colorScheme of ["light", "dark"] as const) {
    // Nothing stored yet: the theme follows the system preference, set before first paint.
    const context = await browser.newContext({ baseURL, colorScheme, reducedMotion: "reduce" });
    const page = await context.newPage();
    await signIn(page);
    expect(await page.locator("html").evaluate((html) => html.classList.contains("dark"))).toBe(
      colorScheme === "dark",
    );
    for (const [name, path] of pages) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await page.screenshot({ path: `shots/theme-${colorScheme}-${name}.png`, fullPage: true });
      await settled(page);
      const { violations } = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      expect(
        violations.map(
          (v) => `${name}: ${v.id} ${v.nodes.map((n) => `${n.target} ${n.any[0]?.message}`).join(", ")}`,
        ),
      ).toEqual([]);
    }
    await context.close();
  }

  // The switch in the header: Dark sticks across a reload, on a light system.
  const context = await browser.newContext({ baseURL, colorScheme: "light" });
  const page = await context.newPage();
  await signIn(page);
  await page.getByRole("button", { name: /^Theme:/ }).click();
  await page.getByRole("menuitemradio", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  await expect(page.getByRole("button", { name: "Theme: Dark" })).toBeVisible();
  await context.close();
});

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

// A fade that is still running would be measured half transparent: let every animation finish.
const settled = (page: Page) =>
  page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished.catch(() => {}))));

async function expectNoViolations(page: Page, name: string) {
  await settled(page);
  const { violations } = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  expect(
    violations.map(
      (v) => `${name}: ${v.id} ${v.nodes.map((n) => `${n.target} ${n.any[0]?.message}`).join(", ")}`,
    ),
  ).toEqual([]);
}

// #427: every page the redesign touched, in both themes and at phone and desktop width, with its
// states that open something (a dialog, results). Runs after the first test: it reads the library
// that test imported.
test("the redesigned pages and their dialogs have no axe violation", async ({ browser }) => {
  test.setTimeout(300_000);
  const pages = [
    ["add-library", "/libraries/new"],
    ["ai", "/ai"],
    ["users", "/users"],
    ["account", "/account"],
    ["global-search", "/search?q=retry_policy"],
    ["global-search-empty", "/search?q=zzzznothingmatches"],
    ["playground", "/playground"],
    ["library", "/libraries/fixture/docs-repo?version=v1.4.0"],
    ["article", "/libraries/fixture/docs-repo?version=v1.4.0&path=docs%2Fguide%2Fresilience.md"],
    ["settings", "/libraries/fixture/docs-repo/settings"],
  ] as const;
  const widths = [
    ["desktop", { width: 1280, height: 900 }],
    ["phone", { width: 390, height: 844 }],
  ] as const;
  for (const colorScheme of ["light", "dark"] as const) {
    for (const [size, viewport] of widths) {
      const context = await browser.newContext({
        baseURL,
        colorScheme,
        viewport,
        reducedMotion: "reduce",
      });
      const page = await context.newPage();
      // The sign-in page is only reachable signed out.
      await page.goto("/sign-in");
      await page.waitForLoadState("networkidle");
      await expectNoViolations(page, `sign-in ${colorScheme} ${size}`);
      await signIn(page);
      for (const [name, path] of pages) {
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        await page.screenshot({
          path: `shots/redesign-${colorScheme}-${size}-${name}.png`,
          fullPage: true,
        });
        await expectNoViolations(page, `${name} ${colorScheme} ${size}`);
      }

      // The playground with results, and the new-token dialog with its secret.
      await page.goto("/playground");
      await page.getByLabel("Query", { exact: true }).fill("retry_policy");
      await page.getByRole("button", { name: "Search" }).click();
      // A fresh instance has no embedding role: hybrid says so, and BM25 still answers.
      await expect(page.getByRole("alert")).toContainText("Unavailable");
      await expectNoViolations(page, `playground error ${colorScheme} ${size}`);
      await page.getByLabel("Mode", { exact: true }).selectOption("bm25");
      await page.getByRole("button", { name: "Search" }).click();
      await expect(page.getByRole("list", { name: /results$/ })).toBeVisible();
      await expectNoViolations(page, `playground results ${colorScheme} ${size}`);

      await page.goto("/account");
      await page.getByRole("button", { name: "New token" }).click();
      await page.getByLabel("Name").fill("axe");
      await expectNoViolations(page, `new-token dialog ${colorScheme} ${size}`);
      await page.getByRole("button", { name: "Create token" }).click();
      await expect(page.getByText("Copy your token now")).toBeVisible();
      await page.screenshot({ path: `shots/redesign-${colorScheme}-${size}-token-secret.png` });
      await expectNoViolations(page, `token secret ${colorScheme} ${size}`);
      await context.close();
    }
  }
});

// #427 round-2 leftovers, kept from coming back: the reader's type sizes, the pills in search
// results, and how much of a phone screen the library page spends on controls.
test("the reader, the search pills and the phone library page keep their proportions", async ({
  browser,
}) => {
  const context = await browser.newContext({
    baseURL,
    viewport: { width: 390, height: 844 },
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  await signIn(page);

  // Reader: no text below 12 px and a short list of sizes (the scale in web/DESIGN.md).
  await page.goto("/libraries/fixture/docs-repo?version=v1.4.0&path=docs%2Fguide%2Fresilience.md");
  await expect(page.locator(".doc-code")).toBeVisible();
  const sizes = await page.locator("main").evaluate((main) => {
    const found = new Map<number, string>();
    const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const el = n.parentElement;
      if (!el || !n.textContent?.trim() || el.closest(".sr-only")) continue;
      const size = Math.round(Number.parseFloat(getComputedStyle(el).fontSize));
      if (!found.has(size)) found.set(size, `${el.tagName.toLowerCase()}.${el.className}`);
    }
    return [...found].sort((a, b) => a[0] - b[0]);
  });
  console.log(`reader font sizes at 390: ${sizes.map(([s, e]) => `${s} (${e})`).join("; ")}`);
  expect(Math.min(...sizes.map(([size]) => size))).toBeGreaterThanOrEqual(12);
  expect(sizes.length).toBeLessThanOrEqual(8);

  // Search pills: 12 px text in a 20 px pill, not the size of the line they sit under.
  await page.goto("/libraries/fixture/docs-repo?version=v1.4.0&q=retry_policy");
  const pill = page.locator('ul[aria-label="Tags"] li').first();
  await expect(pill).toBeVisible();
  const box = await pill.boundingBox();
  expect(box?.height).toBeLessThanOrEqual(24);
  expect(await pill.evaluate((el) => getComputedStyle(el).fontSize)).toBe("12px");

  // Library page: the controls (picker, files, search, tags) end before the first file row.
  await page.goto("/libraries/fixture/docs-repo?version=v1.4.0");
  const tree = page.getByRole("treeitem").first();
  await expect(tree).toBeVisible();
  const band = await page.locator("header").first().boundingBox();
  const first = await tree.boundingBox();
  const stack = (first?.y ?? 0) - ((band?.y ?? 0) + (band?.height ?? 0));
  console.log(`library page at 390: ${Math.round(stack)} px from the band to the first file`);
  expect(stack).toBeLessThanOrEqual(380);
  await context.close();
});

// #427, "lists stay responsive with large libraries": the real UI build in a real browser, with the
// two lists that grow answered from synthetic data (300 libraries in pages of 50; a version of 7,000 articles that
// pages 100 at a time). It records load time, long tasks (> 50 ms) and frame times while scrolling,
// prints them, and fails only on budgets loose enough for a CI machine without a GPU.
async function observeLongTasks(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __long: number[] };
    w.__long = [];
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) w.__long.push(e.duration);
    }).observe({ type: "longtask", buffered: true });
  });
}

const longest = (page: Page) =>
  page.evaluate(() => Math.max(0, ...(window as unknown as { __long: number[] }).__long));

/** Scrolls `selector` (or the page) one step per frame for `ms`; returns the frame times. */
function scrollFrames(page: Page, selector: string | null, ms: number) {
  return page.evaluate(
    ([sel, duration]) =>
      new Promise<{ frames: number; p95: number; max: number }>((resolve) => {
        const el = sel ? document.querySelector(sel) : document.scrollingElement;
        const deltas: number[] = [];
        let last = performance.now();
        const start = last;
        let down = true;
        const tick = (now: number) => {
          deltas.push(now - last);
          last = now;
          if (el) {
            el.scrollTop += down ? 48 : -48;
            if (el.scrollTop + el.clientHeight >= el.scrollHeight - 1 || el.scrollTop <= 0) {
              down = !down;
            }
          }
          if (now - start < Number(duration)) requestAnimationFrame(tick);
          else {
            const sorted = [...deltas].sort((a, b) => a - b);
            resolve({
              frames: deltas.length,
              p95: sorted[Math.floor(sorted.length * 0.95)] ?? 0,
              max: sorted.at(-1) ?? 0,
            });
          }
        };
        requestAnimationFrame(tick);
      }),
    [selector, ms] as const,
  );
}

test("the library list and the file tree stay responsive with large libraries", async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const context = await browser.newContext({
    baseURL,
    viewport: { width: 1280, height: 900 },
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  await observeLongTasks(page);
  await signIn(page);

  // 300 libraries: the real first one, copied.
  const real = await (await page.request.get("/api/v1/libraries")).json();
  const base = real.libraries[0];
  const bulk = Array.from({ length: 300 }, (_, i) => ({
    ...base,
    id: `/bulk/lib-${i}`,
    title: `Library ${i}`,
  }));
  // The API pages by cursor (an offset here); the list asks for 50 at a time.
  await page.route(/\/api\/v1\/libraries\?/, (route) => {
    const q = new URL(route.request().url()).searchParams;
    const from = Number(q.get("cursor") ?? 0);
    const limit = Number(q.get("limit") ?? 50);
    return route.fulfill({
      json: {
        ...real,
        libraries: bulk.slice(from, from + limit),
        total: bulk.length,
        next_cursor: from + limit < bulk.length ? String(from + limit) : null,
      },
    });
  });
  const started = Date.now();
  await page.goto("/");
  // The first page is 50 libraries of 300, and says so; the rest is one button away.
  await expect(page.getByText("Showing 50 of 300")).toBeVisible();
  await expect(page.getByRole("link", { name: "Library 49", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Library 299", exact: true })).toHaveCount(0);
  const firstMs = Date.now() - started;
  for (let shown = 50; shown < 300; shown += 50) {
    await page.getByRole("button", { name: "Load more" }).click();
    await expect(page.getByText(`Showing ${shown + 50} of 300`)).toBeVisible();
  }
  await expect(page.getByRole("link", { name: "Library 299", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(0);
  const listMs = Date.now() - started;
  const nodes = await page.evaluate(() => document.querySelectorAll("*").length);
  const list = await scrollFrames(page, null, 1500);
  console.log(
    `300 libraries in pages of 50: first page in ${firstMs} ms, all loaded in ${listMs} ms, ${nodes} DOM nodes, longest task ${Math.round(await longest(page))} ms, scroll frames p95 ${Math.round(list.p95)} ms max ${Math.round(list.max)} ms`,
  );
  expect(firstMs).toBeLessThan(4000);
  expect(listMs).toBeLessThan(8000);
  expect(await longest(page)).toBeLessThan(1000);
  expect(list.p95).toBeLessThan(50);
  await page.unroute(/\/api\/v1\/libraries\?/);

  // One version of 7,000 articles, paged 100 at a time like the API does.
  // One flat folder is the worst case for the DOM: every file is a row.
  const all = Array.from({ length: 7000 }, (_, i) => `page-${String(i).padStart(4, "0")}.md`);
  await page.route(/\/api\/v1\/libraries\/fixture\/docs-repo\/articles\?/, (route) => {
    const q = new URL(route.request().url()).searchParams;
    const prefix = q.get("path_prefix") ?? "";
    const from = Number(q.get("cursor") ?? 0);
    const limit = Number(q.get("limit") ?? 100);
    const matching = all.filter((p) => p.startsWith(prefix));
    const slice = matching.slice(from, from + limit);
    return route.fulfill({
      json: {
        articles: slice.map((path) => ({ path, title: "", tags: [], size: 100 })),
        next_cursor: from + limit < matching.length ? String(from + limit) : null,
      },
    });
  });
  await page.goto("/libraries/fixture/docs-repo?version=v1.4.0");
  const more = page.getByRole("treeitem", { name: /Show more/ });
  const treeStart = Date.now();
  for (let i = 0; i < 20; i++) {
    const before = await page.getByRole("treeitem").count();
    await more.click();
    await expect.poll(() => page.getByRole("treeitem").count()).toBeGreaterThan(before);
  }
  const pagingMs = Date.now() - treeStart;
  const rows = await page.getByRole("treeitem").count();
  const tree = await scrollFrames(page, "#file-tree > div:last-child", 1500);
  console.log(
    `file tree after 20 pages: ${rows} rows, ${pagingMs} ms to click through, longest task ${Math.round(await longest(page))} ms, scroll frames p95 ${Math.round(tree.p95)} ms max ${Math.round(tree.max)} ms`,
  );
  expect(rows).toBeGreaterThan(1500);
  expect(await longest(page)).toBeLessThan(1000);
  expect(tree.p95).toBeLessThan(50);
  await context.close();
});
