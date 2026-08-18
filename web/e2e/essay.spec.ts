import { type Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const MOCK = "http://127.0.0.1:8099";

test.use({ video: "on" });

async function ask(page: Page, caseText: string, question: string) {
  await page.goto("/");
  await page.getByPlaceholder("A polity or set of polities").fill(caseText);
  await page.getByPlaceholder("Ask a question").fill(question);
  await page.getByRole("button", { name: "Ask" }).click();
}

test.beforeEach(async ({ request }) => {
  await request.post(`${MOCK}/__reset`);
});

// "Beirut" is the mock's essay fixture (`e2e/mock-service.mjs`); every other
// case -- "Damascus" among them -- carries no essay, the shape
// `paper.spec.ts` already exercises unedited.

test("the essay is the answer; the claim list opens from behind its own disclosure, unchanged", async ({
  page,
}) => {
  await ask(page, "Beirut", "Did Mandate recruitment shape later rule?");

  const essay = page.getByTestId("essay");
  await expect(essay).toBeVisible({ timeout: 20_000 });

  // The thesis, as the H1 the reader render already produces.
  await expect(
    essay.getByRole("heading", {
      level: 1,
      name: "Mandate recruitment set the pattern the Ba'th later inherited.",
    }),
  ).toBeVisible();

  // Every section heading, in plan order.
  await expect(essay.getByRole("heading", { level: 2, name: "What the question asks" })).toBeVisible();
  await expect(essay.getByRole("heading", { level: 2, name: "The mandate's bureaucracy" })).toBeVisible();
  await expect(essay.getByRole("heading", { level: 2, name: "Reading Batatu against Vignal" })).toBeVisible();

  // No claim rail on screen -- the claim list sits behind its own disclosure.
  await expect(page.getByTestId("paper")).not.toBeVisible();
  await expect(page.getByTestId("no-essay")).toHaveCount(0);

  await page.screenshot({ path: "test-results/evidence/essay-present.png", fullPage: true });

  // Opening the disclosure reveals the same claim list `paper.spec.ts`
  // asserts directly against -- markers, rail and legend, unmoved.
  await page.getByTestId("claims-disclosure").getByText("Claims", { exact: true }).click();

  const paper = page.getByTestId("paper");
  await expect(paper.getByText("stated", { exact: true })).toBeVisible();
  await expect(paper.getByText("concluded across 3 sources")).toBeVisible();
  await expect(paper.getByText("runs past the books")).toBeVisible();
  await expect(page.getByTestId("legend")).toBeVisible();

  await page.screenshot({ path: "test-results/evidence/essay-claims-opened.png", fullPage: true });
});

test("an ask with no essay states the absence plainly and shows the claim list", async ({ page }) => {
  await ask(page, "Damascus", "Did Mandate recruitment shape later rule?");

  await expect(page.getByTestId("paper")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("essay")).toHaveCount(0);

  const notice = page.getByTestId("no-essay");
  await expect(notice).toBeVisible();
  await expect(notice).toHaveText("No essay was drafted for this answer.");

  // The claim list itself, visible with no click -- never presented as the
  // intended answer, but not hidden either.
  const paper = page.getByTestId("paper");
  await expect(paper.getByText("stated", { exact: true })).toBeVisible();

  await page.screenshot({ path: "test-results/evidence/essay-absent.png", fullPage: true });
});
