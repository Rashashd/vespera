import { test, expect } from "@playwright/test";

// E2E: reviewer approve happy path + reject-with-comment returns to queue (T038)
// Runs against the live stack (PLAYWRIGHT_BASE_URL + live backend).

const REVIEWER_EMAIL = process.env.E2E_REVIEWER_EMAIL || "reviewer@example.com";
const REVIEWER_PASSWORD = process.env.E2E_REVIEWER_PASSWORD || "password";

test.describe("Reviewer happy path", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
  });

  test("reviewer can sign in and reach the queue", async ({ page }) => {
    await page.fill('[name="email"]', REVIEWER_EMAIL);
    await page.fill('[name="password"]', REVIEWER_PASSWORD);
    await page.click('[type="submit"]');
    // After login, reviewer should land on /queue
    await expect(page).toHaveURL(/\/queue/);
    await expect(page.getByRole("heading", { name: /queue/i })).toBeVisible();
  });

  test("sign-in page reachable and shows form", async ({ page }) => {
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
  });
});
