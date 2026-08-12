import { type Page } from "@playwright/test";
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

test("an ask runs to completion and the walk is visible the whole time", async ({ page }) => {
  await ask(page, "Syria", "Did the Mandate's administration shape later Ba'thist rule?");

  const events = page.getByTestId("walk-events").getByRole("listitem");
  await expect(events.first()).toContainText("Interrogated the question");
  await expect(page.getByLabel("Elapsed")).toBeVisible();

  // The mock drops the first connection after two events with the job still
  // running. The client resumes with `Last-Event-ID`, so the walk ends up with
  // every event exactly once.
  await expect(events).toHaveCount(4);
  await expect(events.nth(3)).toContainText("Checked every claim");

  await expect(page.getByTestId("paper")).toBeVisible();
  await expect(page.getByTestId("ask-error")).toHaveCount(0);
});

// A real ask runs for minutes and is quiet for most of them. Any hop between
// the browser and the service that buffers -- Next's own gzip did, #748 -- is
// invisible to a mock that answers instantly, because the buffer flushes when
// the stream closes and every event lands at once. So the assertion is that
// the early events are on screen *while the ask is still running*.
test("the walk shows what has happened while the stream is still open and quiet", async ({
  page,
}) => {
  await ask(page, "quiet", "Did the Mandate's administration shape later Ba'thist rule?");

  const events = page.getByTestId("walk-events").getByRole("listitem");
  await expect(events).toHaveCount(2);
  await expect(page.getByTestId("paper")).toHaveCount(0);

  // And the silence is a pause, not the end: the rest still arrives.
  await expect(events).toHaveCount(4, { timeout: 20_000 });
  await expect(page.getByTestId("paper")).toBeVisible();
});

test("killing the API mid-ask shows an error, not a permanent spinner", async ({
  page,
  request,
}) => {
  await ask(page, "Syria", "Did the Mandate's administration shape later Ba'thist rule?");
  await expect(page.getByTestId("walk-events").getByRole("listitem").first()).toBeVisible();

  await request.post(`${MOCK}/__kill`);

  await expect(page.getByTestId("ask-error")).toContainText("Lost contact with the Axial service", {
    timeout: 20_000,
  });
  await expect(page.getByRole("button", { name: "Ask" })).toBeEnabled();
});

// Issue #760: the API dying mid-ask does not strand it. The worker survives
// the restart and keeps running the ask; a reload has to reattach through
// the id `sessionStorage` remembered, replay everything the service has,
// and land on the paper -- missing no event, repeating none.
test("the service dying and coming back doesn't strand a running ask -- reload picks the walk back up", async ({
  page,
  request,
}) => {
  await ask(page, "quiet", "Did the Mandate's administration shape later Ba'thist rule?");

  const events = page.getByTestId("walk-events").getByRole("listitem");
  await expect(events).toHaveCount(2);

  await request.post(`${MOCK}/__kill`);
  await expect(page.getByTestId("ask-error")).toContainText("Lost contact with the Axial service", {
    timeout: 20_000,
  });

  // The worker kept running; the restart loses no job state (`__revive`
  // does not `jobs.clear()`, unlike `__reset`).
  await request.post(`${MOCK}/__revive`);
  await page.reload();

  // No button, no re-typed brief: the reload alone resumes the walk, in
  // order, with none of it repeated and none of it missing.
  await expect(events).toHaveCount(4, { timeout: 20_000 });
  await expect(events.nth(0)).toContainText("Interrogated the question");
  await expect(events.nth(3)).toContainText("Checked every claim");
  await expect(page.getByTestId("paper")).toBeVisible();
  await expect(page.getByTestId("ask-error")).toHaveCount(0);
});

// The other way in (issue #760): a `running` row in History, opened directly,
// with no reload-time reattachment to lean on.
test("a running row in history opens back into the walk, not a paper fetch that would 409", async ({
  page,
}) => {
  await ask(page, "quiet", "Did the Mandate's administration shape later Ba'thist rule?");
  await expect(page.getByTestId("walk-events").getByRole("listitem")).toHaveCount(2);

  // Drop what this tab remembers, so the reload does not auto-reattach --
  // this test is about the History row's own button, not the automatic path
  // the test above already covers.
  await page.evaluate(() => window.sessionStorage.removeItem("axial.liveAsk"));
  await page.reload();
  await expect(page.getByPlaceholder("A polity or set of polities")).toHaveValue("");

  await page.getByTestId("history").getByText("History", { exact: true }).click();
  const row = page.getByTestId("history-list").locator("li").filter({ hasText: "quiet" });
  await expect(row.getByText("running")).toBeVisible();
  await row.getByRole("button", { name: "Resume" }).click();

  const events = page.getByTestId("walk-events").getByRole("listitem");
  await expect(events).toHaveCount(4, { timeout: 20_000 });
  await expect(page.getByTestId("paper")).toBeVisible();
});

test("a refusal is shown in the service's own words", async ({ page }) => {
  await ask(page, "over quota", "One ask too many");
  await expect(page.getByTestId("ask-error")).toContainText(
    "You've reached your daily limit of 20 ask(s).",
  );
});

test.describe("on a machine set to dark", () => {
  test.use({ colorScheme: "dark" });

  // Issue #770: `ThemeControl` collapses to the current choice, so the
  // three mode buttons are only in the DOM once its own `<summary>` is
  // opened -- picking one closes it again, hence opening it back up before
  // the second and third picks below.
  const openThemeControl = (page: Page) =>
    page.getByRole("group", { name: "Theme" }).locator("summary").click();

  test("system follows the machine and an explicit choice overrides it both ways", async ({
    page,
  }) => {
    await page.goto("/");
    const root = page.locator("html");
    await expect(root).toHaveAttribute("data-theme", "dark");
    const darkBackground = await page.evaluate(
      () => getComputedStyle(document.body).backgroundColor,
    );

    await openThemeControl(page);
    await page.getByRole("button", { name: "light" }).click();
    await expect(root).toHaveAttribute("data-theme", "light");
    const lightBackground = await page.evaluate(
      () => getComputedStyle(document.body).backgroundColor,
    );
    expect(lightBackground).not.toBe(darkBackground);

    // The choice outlives the page, and still beats the machine on the way back.
    await page.reload();
    await expect(root).toHaveAttribute("data-theme", "light");

    await openThemeControl(page);
    await page.getByRole("button", { name: "system" }).click();
    await expect(root).toHaveAttribute("data-theme", "dark");
  });
});
