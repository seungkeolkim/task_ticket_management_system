const { test } = require("node:test");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const { filterUrl, condition, authenticatedContext, saveFilter } = require("./filter-helpers.cjs");

/** 개인 조건 저장·복원·이름 변경·덮어쓰기·삭제와 이름 escaping을 검증한다. */
test("personal compound filters support their complete lifecycle", async () => {
  const baseUrl = process.env.TTMS_BROWSER_BASE_URL;
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  try {
    const context = await authenticatedContext(browser, baseUrl);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(filterUrl(baseUrl, "tickets", [condition("type", "in", ["TASK"])], { sort_by: "number", page_size: 10 }));
    const panel = page.locator("[data-saved-filters]");
    const selection = panel.locator("[data-saved-filter-selection]");
    const filterName = "개인 업무 <img src=x onerror=alert(1)>";
    await saveFilter(page, filterName, "personal");
    assert.equal(await selection.locator("option:checked").textContent(), filterName);
    assert.equal(await panel.locator("img").count(), 0);
    assert.match(await panel.locator("[data-saved-filter-feedback]").innerText(), /나에게만 표시/);
    const filterSelection = await selection.inputValue();
    await page.goto(`${baseUrl}/projects/DEV/board`);
    await selection.selectOption(filterSelection);
    await Promise.all([page.waitForNavigation(), page.getByRole("button", { name: "불러오기", exact: true }).click()]);
    const loadedDefinition = JSON.parse(new URL(page.url()).searchParams.get("filter"));
    assert.equal(loadedDefinition.expression.children[0].values[0], "TASK");
    assert.equal(loadedDefinition.page_size, 10);
    assert.equal(await page.locator(".kanban-card").count(), 1);
    await Promise.all([
      page.waitForNavigation(), page.waitForEvent("dialog").then(dialog => dialog.accept("내 등록 업무")),
      page.getByRole("button", { name: "이름 변경", exact: true }).click(),
    ]);
    assert.equal(await selection.locator("option:checked").textContent(), "내 등록 업무");
    await page.goto(filterUrl(baseUrl, "board", [condition("type", "in", ["SUBTASK"])]));
    await selection.selectOption(filterSelection);
    await Promise.all([
      page.waitForNavigation(), page.waitForEvent("dialog").then(dialog => dialog.accept()),
      page.getByRole("button", { name: "현재 조건으로 덮어쓰기", exact: true }).click(),
    ]);
    await page.getByRole("link", { name: "초기화", exact: true }).click();
    await selection.selectOption(filterSelection);
    await Promise.all([page.waitForNavigation(), page.getByRole("button", { name: "불러오기", exact: true }).click()]);
    assert.equal(JSON.parse(new URL(page.url()).searchParams.get("filter")).expression.children[0].values[0], "SUBTASK");
    assert.equal(await page.locator(".kanban-card").count(), 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await Promise.all([
      page.waitForNavigation(), page.waitForEvent("dialog").then(dialog => dialog.accept()),
      page.getByRole("button", { name: "삭제", exact: true }).click(),
    ]);
    assert.equal(await selection.locator(`option[value="${filterSelection}"]`).count(), 0);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
