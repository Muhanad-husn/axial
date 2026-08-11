import { expect, test, type Page } from "@playwright/test";

const MOCK = "http://127.0.0.1:8099";

async function askAndWaitForPaper(page: Page, caseText: string, question: string) {
  await page.goto("/");
  await page.getByPlaceholder("A polity or set of polities").fill(caseText);
  await page.getByPlaceholder("Ask a question").fill(question);
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByTestId("paper")).toBeVisible({ timeout: 20_000 });
}

test.beforeEach(async ({ request }) => {
  await request.post(`${MOCK}/__reset`);
});

// "Damascus" is the mock's default fixture -- shaped like `locator` citation
// mode, no `citation.quote` anywhere. "Aleppo" is shaped like `passage`
// mode instead (`e2e/mock-service.mjs`). The client holds no opinion about
// which is live (#690), so both are exercised here rather than one.

test("every claim carries its evidence marker, in locator mode", async ({ page }) => {
  await askAndWaitForPaper(page, "Damascus", "Did Mandate recruitment shape later rule?");

  const paper = page.getByTestId("paper");
  await expect(paper.getByText("stated", { exact: true })).toBeVisible();
  await expect(paper.getByText("concluded across 3 sources")).toBeVisible();
  await expect(paper.getByText("runs past the books")).toBeVisible();

  // The (a) claim's citation -- author, chapter, section, never a page
  // number (none exists anywhere in this system).
  await expect(paper.getByText("Batatu (1999) · ch. 8 · Troupes Spéciales recruitment")).toBeVisible();

  // The (c) claim's empty grounds render as a correct value, not a gap.
  await expect(paper.getByText("no supporting passage")).toBeVisible();

  // Locator mode: no quoted passage anywhere on the page.
  await expect(page.getByText("Recruitment followed administrative convenience")).toHaveCount(0);

  // The legend spells the three markers out.
  const legend = page.getByTestId("legend");
  await expect(legend.getByText("A source says this directly.")).toBeVisible();
  await expect(legend.getByText("Axial put sources together. Most likely to be wrong.")).toBeVisible();
  await expect(legend.getByText("Beyond what the books support. Labelled, not removed.")).toBeVisible();
});

test("the same paper carries quoted passages in passage mode", async ({ page }) => {
  await askAndWaitForPaper(page, "Aleppo", "Did Mandate recruitment shape later rule?");

  const paper = page.getByTestId("paper");
  await expect(paper.getByText("stated", { exact: true })).toBeVisible();
  await expect(paper.getByText("concluded across 3 sources")).toBeVisible();
  await expect(
    paper.getByText("Recruitment followed administrative convenience, not a stated policy."),
  ).toBeVisible();
});

test("the metrics panel is shut until opened and sits outside the paper", async ({ page }) => {
  await askAndWaitForPaper(page, "Damascus", "Did Mandate recruitment shape later rule?");

  const panel = page.getByTestId("metrics-panel");
  await expect(panel.getByText("Total:")).not.toBeVisible();

  // Telemetry never leaks into the paper's own prose.
  await expect(page.getByTestId("paper").getByText("$0.13")).toHaveCount(0);

  await panel.getByText("Metrics", { exact: true }).click();
  await expect(panel.getByText("Total: $0.13")).toBeVisible();
  await expect(panel.getByText("dense", { exact: false })).toBeVisible();
});

test("all three export formats download", async ({ page }) => {
  await askAndWaitForPaper(page, "Damascus", "Did Mandate recruitment shape later rule?");

  await page.getByTestId("export").getByText("Export", { exact: true }).click();

  for (const [label, extension] of [
    ["Markdown (.md)", ".md"],
    ["Word (.docx)", ".docx"],
    ["OpenDocument (.odt)", ".odt"],
  ] as const) {
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("export").getByRole("link", { name: label }).click(),
    ]);
    expect(download.suggestedFilename()).toContain(extension);
  }
});
