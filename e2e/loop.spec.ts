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
  await expect(page.getByText(/^\d+ files imported/)).toBeVisible({ timeout: 60_000 });
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
      const { violations } = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      expect(
        violations.map((v) => `${name}: ${v.id} ${v.nodes.map((n) => n.target).join(", ")}`),
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
