import { type Page } from "@playwright/test";
import { ANALYST_A_ID, ANALYST_B_ID, clearSession, seedSession } from "./auth";
import { expect, test } from "./fixtures";

const MOCK = "http://127.0.0.1:8099";

async function ask(page: Page, caseText: string, question: string) {
  await page.goto("/");
  await page.getByPlaceholder("A polity or set of polities").fill(caseText);
  await page.getByPlaceholder("Ask a question").fill(question);
  await page.getByRole("button", { name: "Ask" }).click();
}

test.beforeEach(async ({ request }) => {
  await request.post(`${MOCK}/__reset`);
});

// Issue #764's first "done when" bullet: the same #687 flow, now as a named
// person. `fixtures.ts`'s own `context` fixture already signs every spec in
// as `DEFAULT_USER_ID`; this test is the one that says so explicitly and
// checks the door that makes it possible -- a sign-out control that returns
// to the gate.
test("a signed-in analyst asks, watches the walk, reads the paper -- and can sign out back to the gate", async ({
  page,
}) => {
  await ask(page, "Syria", "Did the Mandate's administration shape later Ba'thist rule?");
  await expect(page.getByTestId("paper")).toBeVisible({ timeout: 20_000 });

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();
  await expect(page.getByTestId("paper")).toHaveCount(0);
});

// Issue #764's second "done when" bullet.
test.describe("signed out", () => {
  test.use({
    context: async ({ context }, use) => {
      // Override the auto-signed-in default (`fixtures.ts`) for this
      // describe block only -- these tests are about the gate itself.
      await clearSession(context);
      // eslint-disable-next-line react-hooks/rules-of-hooks -- Playwright's fixture API, not a React hook.
      await use(context);
    },
  });

  test("a signed-out visitor lands on sign-in, not an app that silently 401s", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();
    await expect(page.getByPlaceholder("A polity or set of polities")).toHaveCount(0);
  });

  // A "deep link to another analyst's ask id": this browser still remembers
  // a live-ask id from a previous, signed-in session (exactly what sign-out
  // is supposed to have cleared, and does -- `session.ts`'s own
  // `axial.liveAsk`). Even if it didn't, the gate sits ahead of the
  // reattachment logic entirely: nothing under it ever mounts while signed
  // out, so there is nothing left to leak into.
  test("a stale live-ask id left in this browser is never reattached to while signed out", async ({
    page,
  }) => {
    await page.addInitScript(() => {
      window.sessionStorage.setItem("axial.liveAsk", "someone-elses-ask");
    });
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();
    await expect(page.getByTestId("walk-events")).toHaveCount(0);
    await expect(page.getByTestId("paper")).toHaveCount(0);
  });
});

// Issue #764's third "done when" bullet.
test("two analysts in turn on the same browser see two different histories and two different themes", async ({
  page,
  context,
}) => {
  await seedSession(context, ANALYST_A_ID);
  await ask(page, "Analyst A's own case", "A question only analyst A asked");
  await expect(page.getByTestId("paper")).toBeVisible({ timeout: 20_000 });

  await page.getByTestId("history").getByText("History", { exact: true }).click();
  await expect(page.getByTestId("history-list").getByText("Analyst A's own case")).toBeVisible();

  // Issue #770: `ThemeControl` collapses to the current choice -- open it
  // before its mode buttons are in the DOM to click.
  await page.getByRole("group", { name: "Theme" }).locator("summary").click();
  await page.getByRole("button", { name: "dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();

  // Analyst B signs in on the very same browser.
  await seedSession(context, ANALYST_B_ID);
  await page.reload();
  await expect(page.getByPlaceholder("A polity or set of polities")).toBeVisible();

  // No trace of A's history.
  await page.getByTestId("history").getByText("History", { exact: true }).click();
  await expect(page.getByTestId("history-list").getByText("Analyst A's own case")).toHaveCount(0);

  // No trace of A's theme -- B's own profile is `system` by default, never
  // the `dark` A just chose.
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", "dark");

  await page.getByRole("group", { name: "Theme" }).locator("summary").click();
  await page.getByRole("button", { name: "light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  // B's own choice survives a reload, on B's own profile.
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

// Issue #764's fourth "done when" bullet. "Syria" (not "quiet") is the mock's
// case that drops its first connection after two events, forcing a
// reconnect -- `POST /__expire` lands before that reconnect fires, so the
// reconnect itself is what surfaces the now-refused token.
test("a token that expires mid-walk produces a sign-in prompt, not a stuck screen", async ({
  page,
  request,
}) => {
  await ask(page, "Syria", "Did the Mandate's administration shape later Ba'thist rule?");
  await expect(page.getByTestId("walk-events").getByRole("listitem").first()).toBeVisible();

  await request.post(`${MOCK}/__expire`);

  await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByTestId("walk-events")).toHaveCount(0);
});
