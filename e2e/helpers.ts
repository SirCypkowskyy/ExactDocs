import { expect, type Page } from "@playwright/test";

/** Sign in through the sign-in page; the libraries page is where it lands. */
export async function signIn(page: Page, username: string, password: string) {
  await page.goto("/sign-in");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Libraries" })).toBeVisible();
}

/** Wait until every animation has finished: a fade still running is half transparent. */
export const settled = (page: Page) =>
  page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished.catch(() => {}))));
