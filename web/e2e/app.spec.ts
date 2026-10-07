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
  // The card recomputes the overall score for the selected factors (the seven
  // switched on by default) from the mock sub-scores, not the API's compositeScore of 77.
  await expect(page.getByTestId("composite-score")).toHaveText("54");
  await expect(page.getByRole("heading", { name: "Midtown, Manhattan" })).toBeVisible();

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

test("points of interest: add two, see the overlap list, remove them", async ({ page }) => {
  await mockApi(page);
  await page.goto("/app");
  await page.getByRole("combobox").first().fill("350 5th");
  await page.getByRole("listbox", { name: "Address suggestions" }).getByRole("option").first().click();
  await expect(page.getByTestId("composite-score")).toBeVisible();

  const add = page.getByRole("button", { name: "Point of interest", exact: true });
  await add.click();
  const first = page.getByRole("combobox", { name: "Point of interest 1 address" });
  // Armed for a pin on the map, and the keyboard stays closed until the box is tapped again.
  await expect(first).toHaveAttribute("placeholder", "Drop a pin");
  await expect(first).not.toBeFocused();
  await first.fill("grand central");
  await page.getByRole("listbox", { name: "Address suggestions" }).last().getByRole("option").first().click();

  await expect(page.getByRole("heading", { name: "Best areas in the overlap" })).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Best areas in the overlap" }).getByRole("button"),
  ).toHaveCount(2);

  // Two points of interest is the most: the pill goes away after the second box opens.
  await add.click();
  await expect(page.getByRole("combobox", { name: "Point of interest 2 address" })).toHaveAttribute(
    "placeholder",
    "Drop a pin",
  );
  await expect(add).toHaveCount(0);

  await page.getByRole("button", { name: "Remove point of interest 2" }).click();
  await expect(add).toBeVisible();
  await page.getByRole("button", { name: "Remove point of interest 1" }).click();
  await expect(page.getByRole("combobox", { name: /Point of interest/ })).toHaveCount(0);
  await expect(add).toBeVisible();
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
  const boxes = page.getByRole("checkbox", { checked: true });
  while ((await boxes.count()) > 0) await boxes.first().uncheck();
  await page.getByRole("checkbox", { name: /^Groceries/ }).check();
  await expect(page.getByRole("checkbox", { checked: true })).toHaveCount(1);
  await expect.poll(value).toBe("100");
  await expect(bestAreas.getByRole("listitem").first()).toContainText("Strongest: Groceries 100");
  await page.getByRole("checkbox", { name: /^Groceries/ }).uncheck();
  await page.getByRole("checkbox", { name: /^Public transit/ }).check();
  await expect(bestAreas.getByRole("listitem").first()).toContainText("Strongest: Public transit");
  // Everything on again: the two sides average out, so nothing scores 100.
  const off = page.getByRole("checkbox", { checked: false });
  while ((await off.count()) > 0) await off.first().check();
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
  await page.getByRole("button", { name: "Ask Benri" }).click();
  await expect(page.getByRole("region", { name: "Ask Benri" })).toBeVisible();
  await page.getByLabel("Your question").fill("Where is quiet?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Try the Upper West Side.")).toBeVisible();
  const feedback: unknown[] = [];
  await mockApi(page, { feedback });
  await page.getByRole("button", { name: /^Yes/ }).click();
  await expect(page.getByText("Thanks, that helps us improve.")).toBeVisible();
});

test("chat opens inline, filters stay usable, close returns the button", async ({ page }) => {
  await mockApi(page);
  await page.goto("/app?chat=1");
  const chat = page.getByRole("region", { name: "Ask Benri" });
  await expect(chat).toBeVisible();
  await expect(page.getByLabel("Your question")).toBeFocused();
  await expect(page.getByRole("heading", { name: "Factors" })).toBeVisible();
  await page.getByRole("checkbox", { name: /Cafes/ }).click();
  await expect(page.getByRole("checkbox", { name: /Cafes/ })).not.toBeChecked();
  const log = chat.getByRole("log", { name: "Conversation" });
  const box = await log.boundingBox();
  const viewport = page.viewportSize();
  expect(box!.height).toBeLessThanOrEqual(Math.min(0.55 * viewport!.height, 520) + 1);
  await chat.getByRole("button", { name: "Close chat" }).click();
  await expect(chat).toBeHidden();
  await expect(page.getByRole("button", { name: "Ask Benri" })).toBeVisible();
});

test("data sources page lists sources", async ({ page }) => {
  await mockApi(page);
  await page.goto("/data");
  await expect(page.getByRole("rowheader", { name: /OpenStreetMap points of interest/ })).toBeVisible();
  await expect(page.getByText("5 days ago")).toBeVisible();
  await expect(page.getByRole("link", { name: "ODbL 1.0" })).toBeVisible();
});
