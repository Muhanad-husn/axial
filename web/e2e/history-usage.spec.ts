import { type Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const MOCK = "http://127.0.0.1:8099";

async function openHistory(page: Page) {
  await page.goto("/");
  await page.getByTestId("history").getByText("History", { exact: true }).click();
  return page.getByTestId("history-list");
}

test.beforeEach(async ({ request }) => {
  await request.post(`${MOCK}/__reset`);
});

test("the analyst's own past asks render, and a cached one is marked as costing nothing", async ({
  page,
}) => {
  const list = await openHistory(page);
  await expect(list.getByRole("listitem")).toHaveCount(3);

  // The cached row is marked as such on the list itself -- not something an
  // analyst has to open the paper to find out -- and it is the only one.
  await expect(list.getByTestId("cached-badge")).toHaveCount(1);
  await expect(list.getByText("cached · no cost")).toBeVisible();

  // The failed row carries the service's own error text.
  await expect(list.getByText("The corpus snapshot could not be bound.")).toBeVisible();

  // Only the two finished, non-failed rows can be reopened.
  await expect(list.getByRole("button", { name: "Reopen" })).toHaveCount(2);
});

test("each row shows the case and question that produced it, not just its state and timestamp (#759)", async ({
  page,
}) => {
  const list = await openHistory(page);

  // Three fixed rows in `mock-service.mjs`, each with a distinct case and
  // question -- rendered, not just carried in the API response.
  await expect(list.getByText("Damascus")).toBeVisible();
  await expect(list.getByText("Did Mandate recruitment shape later rule?")).toBeVisible();
  await expect(list.getByText("Aleppo")).toBeVisible();
  await expect(list.getByText("The same question, asked a second time")).toBeVisible();
  await expect(list.getByText("Homs")).toBeVisible();
  await expect(list.getByText("A question the corpus could not answer")).toBeVisible();

  // The corpus chip is gone (#759): eight characters of a pin that is
  // constant across every row distinguished nothing.
  await expect(list.getByText(/^corpus /)).toHaveCount(0);
});

test("reopening a finished ask shows its paper, not a fresh walk", async ({ page }) => {
  const list = await openHistory(page);
  await list.getByRole("button", { name: "Reopen" }).first().click();

  await expect(page.getByTestId("paper")).toBeVisible();
  await expect(page.getByTestId("walk-events")).toHaveCount(0);
});

test("reopening a cached ask reads its cost as zero, not unknown and not a repeat charge", async ({
  page,
}) => {
  const list = await openHistory(page);
  const cachedRow = list.locator("li").filter({ hasText: "cached · no cost" });
  await cachedRow.getByRole("button", { name: "Reopen" }).click();

  await expect(page.getByTestId("paper")).toBeVisible();
  const panel = page.getByTestId("metrics-panel");
  await panel.getByText("Metrics", { exact: true }).click();
  await expect(panel.getByText("Total: $0.00")).toBeVisible();
});

test("the session meter reads an unknown cost as a dash, never $0.00", async ({ page }) => {
  await page.goto("/");
  const meter = page.getByTestId("usage-session");
  await expect(meter).toContainText("—");
  await meter.locator("summary").click();
  await expect(meter.getByText("Cost (estimate): —")).toBeVisible();
  await expect(meter.getByText("Tokens: —")).toBeVisible();
});

test("the month meter says estimate and labels the two different ask counts", async ({ page }) => {
  await page.goto("/");
  const meter = page.getByTestId("usage-month");
  await expect(meter).toContainText("$4.82");
  await meter.locator("summary").click();
  await expect(meter.getByText("Cost (estimate): $4.82")).toBeVisible();
  await expect(meter.getByText("Asks made: 9")).toBeVisible();
  await expect(meter.getByText("Asks charged against quota: 7")).toBeVisible();
  await expect(meter.getByText("Daily quota: 3 of 20", { exact: false })).toBeVisible();
  await expect(meter.getByText("Monthly quota: 7 of 300", { exact: false })).toBeVisible();
});

test("the meters and the theme control still fit on a phone-width viewport", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 720 });
  await page.goto("/");
  await expect(page.getByTestId("usage-session")).toBeVisible();
  await expect(page.getByTestId("usage-month")).toBeVisible();
  await expect(page.getByRole("group", { name: "Theme" })).toBeVisible();
});
