const { test } = require("node:test");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const { authenticatedContext, addCondition } = require("./filter-helpers.cjs");

/** 필드 추가·타입 전환·복합 그룹·URL·drag 재조회까지 실제 Browser에서 검증한다. */
test("compound filter editor preserves hierarchy, groups and drag reload", async () => {
  const baseUrl = process.env.TTMS_BROWSER_BASE_URL;
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  try {
    const context = await authenticatedContext(browser, baseUrl);
    const page = await context.newPage();
    const browserErrors = [];
    page.on("pageerror", error => browserErrors.push(error.message));
    await page.goto(`${baseUrl}/projects/DEV/board`);
    assert.equal(await page.locator(".filter-condition").count(), 0);
    const rootGroup = page.locator(".filter-group").first();
    await addCondition(rootGroup, "type", "in", ["SUBTASK"]);
    await addCondition(rootGroup, "status", "in", ["TODO"]);
    await addCondition(rootGroup, "search", "contains", ["Browser 하위"]);
    assert.equal(await page.locator("[data-filter-dirty]").isVisible(), true);
    assert.equal(await page.getByRole("button", { name: "필터 저장", exact: true }).isDisabled(), true);
    await Promise.all([page.waitForNavigation(), page.getByRole("button", { name: "적용", exact: true }).click()]);
    assert.equal(await page.locator(".kanban-card").count(), 1);
    assert.match(await page.locator(".parent-reference").innerText(), /상위 Task/);
    assert.equal(await page.locator("[data-board-column]").count(), 5);
    const filteredDefinition = JSON.parse(new URL(page.url()).searchParams.get("filter"));
    assert.equal(filteredDefinition.expression.children.length, 3);
    await page.reload();
    assert.equal(await page.locator(".filter-condition").count(), 3);
    await page.getByRole("link", { name: "☷ 목록 보기" }).click();
    assert.deepEqual(JSON.parse(new URL(page.url()).searchParams.get("filter")), filteredDefinition);
    assert.equal(await page.locator(".ticket-table-row").count(), 1);
    await page.getByRole("link", { name: "칸반 보기", exact: true }).click();
    const card = page.locator(".kanban-card");
    const progressColumn = page.locator('[data-board-column][data-status="IN_PROGRESS"]');
    await Promise.all([
      page.waitForEvent("dialog").then(dialog => dialog.dismiss()),
      card.dragTo(progressColumn, { sourcePosition: { x: 5, y: 5 }, targetPosition: { x: 40, y: 100 } }),
    ]);
    assert.equal(await card.count(), 1);
    await Promise.all([
      page.waitForEvent("dialog").then(dialog => dialog.accept()), page.waitForNavigation(),
      card.dragTo(progressColumn, { sourcePosition: { x: 5, y: 5 }, targetPosition: { x: 40, y: 100 } }),
    ]);
    assert.deepEqual(JSON.parse(new URL(page.url()).searchParams.get("filter")), filteredDefinition);
    assert.equal(await page.locator(".kanban-card").count(), 0);
    assert.match(await page.locator("#board-feedback").innerText(), /상태를 변경했습니다/);

    await page.goto(`${baseUrl}/projects/DEV/board`);
    await rootGroup.getByRole("button", { name: "그룹 추가", exact: true }).click();
    const nestedGroup = rootGroup.locator(":scope > .filter-group").first();
    await addCondition(nestedGroup, "type", "in", ["SUBTASK"]);
    await addCondition(nestedGroup, "status", "not_in", ["TODO"]);
    await rootGroup.locator(":scope > .filter-group-header [data-group-operator]").selectOption("OR");
    const userOptions = JSON.parse(await page.locator("[data-filter-options]").textContent()).users;
    const userIdentifiers = userOptions.map(user => user.id);
    const assigneeRow = await addCondition(rootGroup, "assignee", "in", userIdentifiers);
    assert.equal(await assigneeRow.locator(".filter-value-options input:checked").count(), userIdentifiers.length);
    await assigneeRow.locator("[data-condition-operator]").selectOption("is_empty");
    assert.equal(await assigneeRow.locator(".filter-condition-values input").count(), 0);
    await assigneeRow.locator("[data-condition-field]").selectOption("due_date");
    assert.equal(await assigneeRow.locator('input[type="date"]').count(), 1);
    await assigneeRow.locator("[data-condition-operator]").selectOption("is_empty");
    await nestedGroup.getByLabel("이 그룹 제외 NOT", { exact: true }).check();
    await Promise.all([page.waitForNavigation(), page.getByRole("button", { name: "적용", exact: true }).click()]);
    assert.match(await page.locator("[data-filter-summary]").textContent(), /NOT .* OR /);
    const groupedDefinition = JSON.parse(new URL(page.url()).searchParams.get("filter"));
    assert.equal(groupedDefinition.expression.children[0].negated, true);
    assert.equal(await page.locator(".filter-group.nested").count(), 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    if (process.env.TTMS_BROWSER_SCREENSHOT) await page.screenshot({ path: process.env.TTMS_BROWSER_SCREENSHOT, fullPage: true });
    await page.getByRole("button", { name: "그룹 삭제", exact: true }).click();
    assert.equal(await page.locator(".filter-group.nested").count(), 0);
    await page.getByRole("link", { name: "초기화", exact: true }).click();
    assert.equal(await page.locator(".filter-condition").count(), 0);
    await rootGroup.getByRole("button", { name: "그룹 추가", exact: true }).click();
    await page.getByRole("button", { name: "적용", exact: true }).click();
    assert.match(await page.locator("[data-filter-error]").innerText(), /빈 그룹/);
    await page.getByRole("button", { name: "그룹 삭제", exact: true }).click();
    await addCondition(rootGroup, "assignee", "is_empty");
    await rootGroup.locator(":scope > .filter-group-header").getByLabel("이 그룹 제외 NOT", { exact: true }).check();
    await page.getByRole("button", { name: "담당자 조건 삭제", exact: true }).click();
    assert.equal(await rootGroup.locator(":scope > .filter-group-header").isVisible(), true);
    await rootGroup.locator(":scope > .filter-group-header").getByLabel("이 그룹 제외 NOT", { exact: true }).uncheck();
    assert.deepEqual(browserErrors, []);
  } finally { await browser.close(); }
});
