import { expect, test } from "@playwright/test";

import { mockApi } from "./mockApi";

test("home loads and shows address suggestions", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const box = page.getByRole("combobox", { name: "Address" });
  await box.fill("350 5th");
  const options = page.getByRole("option");
  await expect(options.first()).toContainText("350 5th Ave");
  await expect(page.getByRole("link", { name: /See every source/ })).toHaveAttribute("href", "/data");
});

test("app result flow: pick a suggestion, see the score, pin it to compare", async ({ page }) => {
  await mockApi(page);
  await page.goto("/app");
  await page.getByRole("combobox").first().fill("350 5th");
  await page.getByRole("listbox", { name: "Address suggestions" }).getByRole("option").first().click();
  await expect(page.getByTestId("composite-score")).toHaveText("77");
  await expect(page.getByRole("heading", { name: "350 5th Ave, New York, NY" })).toBeVisible();

  await page
    .getByRole("region", { name: "Selected location" })
    .getByRole("button", { name: /^Compare: / })
    .click();
  await page.getByRole("button", { name: /Compare places \(1\)/ }).click();
  await expect(page.getByRole("dialog", { name: "Compare places" })).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("toggling a factor recolours the map and re-ranks best areas", async ({ page }) => {
  await mockApi(page);
  await page.goto("/app?center=40.75,-73.97&z=12");
  const bestAreas = page.getByRole("region", { name: "Best areas" });
  const firstScore = () => bestAreas.getByRole("listitem").first().locator("[class*=itemScore]");
  const value = async () => (await firstScore().innerText()).match(/\d+/)![0];
  await expect(firstScore()).toBeVisible();
  const all = await value();

  // Groceries only: the west side wins; transit only: the east side does.
  await page.getByRole("button", { name: "Select none" }).click();
  await page.getByRole("checkbox", { name: /^Groceries/ }).check();
  await expect(page.getByText("1 of 13 on")).toBeVisible();
  await expect.poll(value).toBe("100");
  await expect(bestAreas.getByRole("listitem").first()).toContainText("Strongest: Groceries 100");
  await page.getByRole("checkbox", { name: /^Groceries/ }).uncheck();
  await page.getByRole("checkbox", { name: /^Public transit/ }).check();
  await expect(bestAreas.getByRole("listitem").first()).toContainText("Strongest: Public transit");
  // Everything on again: the two sides average out, so nothing scores 100.
  await page.getByRole("button", { name: "Select all" }).click();
  await expect.poll(value).not.toBe("100");
  expect(all).not.toBe("100");
});

test("falls back to the API when the score file is unavailable", async ({ page }) => {
  await mockApi(page, { noScoreFile: true });
  await page.goto("/app?center=40.75,-73.97&z=12");
  await expect(page.getByRole("heading", { name: "Best areas" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Factors" })).toBeVisible();
});

test("chat panel opens", async ({ page }) => {
  await mockApi(page);
  await page.goto("/app");
  await page.getByRole("button", { name: "Ask BenriSpace" }).click();
  await expect(page.getByRole("region", { name: "Ask BenriSpace" })).toBeVisible();
  await page.getByLabel("Your question").fill("Where is quiet?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Try the Upper West Side.")).toBeVisible();
  const feedback: unknown[] = [];
  await mockApi(page, { feedback });
  await page.getByRole("button", { name: /^Yes/ }).click();
  await expect(page.getByText("Thanks, that helps us improve.")).toBeVisible();
});

test("data sources page lists sources", async ({ page }) => {
  await mockApi(page);
  await page.goto("/data");
  await expect(page.getByRole("rowheader", { name: /OpenStreetMap points of interest/ })).toBeVisible();
  await expect(page.getByText("5 days ago")).toBeVisible();
  await expect(page.getByRole("link", { name: "ODbL 1.0" })).toBeVisible();
});
